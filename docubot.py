"""
Core DocuBot class responsible for:
- Loading documents from the docs/ folder
- Building a simple retrieval index (Phase 1)
- Retrieving relevant snippets (Phase 1)
- Supporting retrieval only answers
- Supporting RAG answers when paired with Gemini (Phase 2)
"""

import os
import glob
import re

MIN_CHUNK_CHARS = 40
MIN_EVIDENCE_SCORE = 2
DEFAULT_TOP_K = 3

REFUSAL_MESSAGE = "I'm not so sure based on these docs."

_PUNCT_STRIP = ".,!?;:\"'()[]{}`*_#/_-"


def _tokenize(text):
    """Lowercase whitespace tokens with light punctuation stripping."""
    words = []
    for raw in text.lower().split():
        token = raw.strip(_PUNCT_STRIP)
        if len(token) >= 3:
            words.append(token)
    return words


class DocuBot:
    def __init__(self, docs_folder="docs", llm_client=None):
        """
        docs_folder: directory containing project documentation files
        llm_client: optional Gemini client for LLM based answers
        """
        self.docs_folder = docs_folder
        self.llm_client = llm_client

        self.documents = self.load_documents()
        self.chunks = []  # List of (filename, chunk_text)
        self.index = self.build_index(self.documents)

    # -----------------------------------------------------------
    # Document Loading
    # -----------------------------------------------------------

    def load_documents(self):
        """
        Loads all .md and .txt files inside docs_folder.
        Returns a list of tuples: (filename, text)
        """
        docs = []
        pattern = os.path.join(self.docs_folder, "*.*")
        for path in glob.glob(pattern):
            if path.endswith(".md") or path.endswith(".txt"):
                with open(path, "r", encoding="utf8") as f:
                    text = f.read()
                filename = os.path.basename(path)
                docs.append((filename, text))
        return docs

    # -----------------------------------------------------------
    # Chunking
    # -----------------------------------------------------------

    def split_chunks(self, text):
        """
        Prefer markdown sections (heading + following paragraphs).
        Fall back to blank-line blocks for non-section text.
        Skip tiny blocks (e.g. bare headings with no body).
        """
        parts = re.split(r"(?=^##\s+)", text, flags=re.MULTILINE)
        chunks = []

        for part in parts:
            part = part.strip()
            if not part:
                continue

            if part.startswith("##") and len(part) >= MIN_CHUNK_CHARS:
                chunks.append(part)
                continue

            for block in part.split("\n\n"):
                chunk = block.strip()
                if len(chunk) >= MIN_CHUNK_CHARS:
                    chunks.append(chunk)

        return chunks

    # -----------------------------------------------------------
    # Index Construction (Phase 1)
    # -----------------------------------------------------------

    def build_index(self, documents):
        """
        Build an inverted index: word -> list of chunk indices.
        self.chunks holds (filename, text) for each index.
        """
        self.chunks = []
        index = {}

        for filename, text in documents:
            for chunk in self.split_chunks(text):
                chunk_idx = len(self.chunks)
                self.chunks.append((filename, chunk))
                for word in _tokenize(chunk):
                    if word not in index:
                        index[word] = []
                    if chunk_idx not in index[word]:
                        index[word].append(chunk_idx)

        return index

    # -----------------------------------------------------------
    # Scoring and Retrieval (Phase 1)
    # -----------------------------------------------------------

    def _term_in_text(self, word, text_lower):
        """True if word appears, or a 6-char prefix matches (generated ~ generation)."""
        if word in text_lower:
            return True
        return len(word) >= 6 and word[:6] in text_lower

    def score_chunk(self, query_words, text):
        """Count how many query words appear in the chunk."""
        text_lower = text.lower()
        score = 0
        for word in query_words:
            if self._term_in_text(word, text_lower):
                score += 1
        return score

    def score_document(self, query, text):
        """Backward-compatible wrapper around score_chunk."""
        return self.score_chunk(_tokenize(query), text)

    def _heading_overlap(self, query_words, text):
        """Tie-break: how many query words hit the markdown heading line."""
        first = text.split("\n", 1)[0]
        if not first.lstrip().startswith("#"):
            return 0
        return self.score_chunk(query_words, first)

    def _min_evidence_score(self, query_words):
        """Need at least 2 word hits, or 1 for a single-word query."""
        if not query_words:
            return 1
        return min(MIN_EVIDENCE_SCORE, len(query_words))

    def retrieve(self, query, top_k=DEFAULT_TOP_K):
        """
        Return top_k (filename, chunk) pairs sorted by score descending.
        Returns [] when no chunk meets the evidence threshold.
        """
        query_words = _tokenize(query)
        if not query_words:
            return []

        min_score = self._min_evidence_score(query_words)

        candidates = set()
        for word in query_words:
            if word in self.index:
                candidates.update(self.index[word])

        scored = []
        for chunk_idx in candidates:
            filename, text = self.chunks[chunk_idx]
            score = self.score_chunk(query_words, text)
            if score >= min_score:
                heading = self._heading_overlap(query_words, text)
                scored.append((score, heading, filename, text))

        scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return [(filename, text) for _, _, filename, text in scored[:top_k]]

    # -----------------------------------------------------------
    # Answering Modes
    # -----------------------------------------------------------

    def answer_retrieval_only(self, query, top_k=DEFAULT_TOP_K):
        """
        Phase 1 retrieval only mode.
        Returns raw chunks and filenames with no LLM involved.
        """
        snippets = self.retrieve(query, top_k=top_k)

        if not snippets:
            return REFUSAL_MESSAGE

        formatted = []
        for filename, text in snippets:
            formatted.append(f"[{filename}]\n{text}\n")

        return "\n---\n".join(formatted)

    def answer_rag(self, query, top_k=DEFAULT_TOP_K):
        """
        Phase 2 RAG mode.
        Uses retrieval to select chunks, then asks Gemini to answer from them.
        """
        if self.llm_client is None:
            raise RuntimeError(
                "RAG mode requires an LLM client. Provide a GeminiClient instance."
            )

        snippets = self.retrieve(query, top_k=top_k)

        if not snippets:
            return REFUSAL_MESSAGE

        return self.llm_client.answer_from_snippets(query, snippets)

    # -----------------------------------------------------------
    # Bonus Helper: concatenated docs for naive generation mode
    # -----------------------------------------------------------

    def full_corpus_text(self):
        """
        Returns all documents concatenated into a single string.
        This is used in Phase 0 for naive 'generation only' baselines.
        """
        return "\n\n".join(text for _, text in self.documents)
