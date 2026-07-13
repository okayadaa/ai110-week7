# DocuBot Model Card

This model card is a short reflection on your DocuBot system. Fill it out after you have implemented retrieval and experimented with all three modes:

1. Naive LLM over full docs  
2. Retrieval only  
3. RAG (retrieval plus LLM)

Use clear, honest descriptions. It is fine if your system is imperfect.

---

## 1. System Overview

**What is DocuBot trying to do?**  

DocuBot is a lightweight retrieval argumented assistant that reads your local docs, find relevant information and generates reliable and accurate answers. 

**What inputs does DocuBot take?**  
For example: user question, docs in folder, environment variables.

User would type a natural language question in the CLI. All the .md and .txt files would be in the docs/ folder where API_REFERENCE, AUTH, DATABASE, and SETUP are stored. The environment variables GEMINI_API_KEY is loaded from .env 

**What outputs does DocuBot produce?**

Each mode provides 3 different outputs where navie generation output sounds confident but is weakly grounded. Retrieval (no LLM) output is only accurate but difficult to interpret, and RAG output has a balance of clarity and reducing hallucinations

---

## 2. Retrieval Design

**How does your retrieval system work?**  
Describe your choices for indexing and scoring.

- How do you turn documents into an index?
- How do you score relevance for a query?
- How do you choose top snippets?

Docs are split into chunks mostly by markdown `##` sections (or blank-line paragraphs if there is no heading). Tiny pieces under 40 characters are skipped. Each chunk is tokenized into lowercase words (punctuation stripped), and those words go into a simple inverted index: word → list of chunk IDs.

For a query, I tokenize the question the same way, look up candidate chunks from the index, and score each chunk by how many query words appear in it. Longer words can also match a 6-character prefix (so something like “generated” can still hit “generation”). Chunks need at least 2 overlapping words in most cases (or 1 if the query is only one useful word). I sort by score, break ties by how many query words hit the heading line, and return the top 3 snippets.

**What tradeoffs did you make?**  
For example: speed vs precision, simplicity vs accuracy.

I chose a simple keyword index over embeddings, so retrieval is fast and easy to explain, but it can miss paraphrases or synonyms. Section-sized chunks keep answers readable, but they are coarser than sentence-level search. The minimum score and top-3 cutoff cut down noisy hits and keep RAG prompts small, at the cost of sometimes refusing or missing a useful but weakly overlapping snippet.

---

## 3. Use of the LLM (Gemini)

**When does DocuBot call the LLM and when does it not?**  
Briefly describe how each mode behaves.

- Naive LLM mode: Always calls Gemini. It intentionally ignores the docs and answers from general knowledge, so it often sounds confident but is weakly grounded in this project.
- Retrieval only mode: Never calls the LLM. It returns the top matching raw snippets with filenames. Answers are accurate when retrieval works, but harder to read.
- RAG mode: Calls Gemini only after retrieval finds enough evidence. The model answers from those snippets. If retrieval finds nothing useful, DocuBot refuses without calling the LLM.

**What instructions do you give the LLM to keep it grounded?**  
Summarize the rules from your prompt. For example: only use snippets, say "I do not know" when needed, cite files.

In RAG mode, the prompt tells Gemini to: use only the provided snippets; not invent functions, endpoints, filenames, or config values; prefer a direct answer when the snippets support it; briefly cite which file(s) it used; and reply exactly “I'm not so sure based on these docs.” only when the snippets do not support an answer.

---

## 4. Experiments and Comparisons

Run the **same set of queries** in all three modes. Fill in the table with short notes.

You can reuse or adapt the queries from `dataset.py`.

| Query | Naive LLM: helpful or harmful? | Retrieval only: helpful or harmful? | RAG: helpful or harmful? | Notes |
|------|---------------------------------|--------------------------------------|---------------------------|-------|
| Where is the auth token generated? | Harmful — long generic JWT / IdP answer, not from these docs | Helpful — shows Token Generation section, but dense | Helpful — names `generate_access_token` in `auth_utils.py` and cites AUTH.md | Best example of the three-mode contrast |
| How do I connect to the database? | Harmful — generic DB advice | Helpful — DATABASE_URL / connection chunk, raw | Helpful — clear step from snippets | Retrieval already has the answer; RAG just makes it easier |
| Which endpoint lists all users? | Harmful / risky — may guess a common REST path | Helpful but noisy — big User Data Endpoints section | Helpful — states `GET /api/users` (admin-only) and cites API_REFERENCE.md | Retrieval buried the answer; RAG surfaced it |
| How does a client refresh an access token? | Harmful — generic OAuth refresh flow | Helpful — Client Workflow + `/api/refresh` snippets | Helpful — short grounded refresh steps with citations | Naive sounds polished but does not match this app |

**What patterns did you notice?**  

- When does naive LLM look impressive but untrustworthy?  
  On auth and token questions. It writes fluent “best practice” answers that ignore `AUTH.md`, so a developer could follow the wrong flow.
- When is retrieval only clearly better?  
  When you need exact project wording and filenames, or when the LLM is down / rate-limited. You see the evidence even if it is messy.
- When is RAG clearly better than both?  
  When the answer is in the docs but spread across a long chunk. RAG turns raw snippets into a short, cited answer without inventing details.

---

## 5. Failure Cases and Guardrails

**Describe at least two concrete failure cases you observed.**  
For each one, say:

- What was the question?  
- What did the system do?  
- What should have happened instead?

**Failure case 1:** “Where is the auth token generated?”  
Early on, RAG said “I'm not so sure based on these docs.” even though AUTH.md explains tokens are created by `generate_access_token` in `auth_utils.py`. Retrieval was ranking weaker chunks, and an older, more cautious prompt refused. It should have answered from the Token Generation section and cited AUTH.md.

**Failure case 2:** “Which endpoint returns all users?” in RAG mode  
Retrieval found the right API section, but Gemini returned a 503 high-demand error, so the user got an API failure instead of an answer. It should either retry, fall back to showing the retrieved snippets, or tell the user to try again later / use retrieval-only mode.

**When should DocuBot say “I do not know based on the docs I have”?**  
Give at least two specific situations.

1. The topic is not in the docs at all (for example payment processing, or “what’s C++ / Python”).  
2. Retrieval finds chunks, but they do not actually answer the question (weak keyword overlap only).

**What guardrails did you implement?**  
Examples: refusal rules, thresholds, limits on snippets, safe defaults.

- Minimum evidence score: usually need at least 2 query-word hits before trusting a chunk.  
- Cap retrieval at top 3 snippets so the LLM sees a small, focused context.  
- If no chunk clears the threshold, refuse before calling Gemini.  
- RAG prompt forbids inventing APIs/config and uses a fixed refusal string when unsupported.  
- Naive mode stays ungrounded on purpose for comparison; RAG is the constrained path.

---

## 6. Limitations and Future Improvements

**Current limitations**  
List at least three limitations of your DocuBot system.

1. Keyword overlap misses paraphrases and near-synonyms unless a light prefix match happens to help.  
2. Section-sized chunks can be large and noisy, so retrieval-only answers dump more text than needed.  
3. RAG depends on Gemini availability; API errors (like 503) can fail even when retrieval succeeded.  
4. Naive mode does not use the docs at all, so it is useful for demos but unsafe as a real product path.

**Future improvements**  
List two or three changes that would most improve reliability or usefulness.

1. Better ranking (embeddings or BM25) so the right section wins more often on paraphrased questions.  
2. If the LLM call fails, fall back to retrieval-only snippets instead of only an error message.  
3. Smaller or overlapping chunks so “lists all users” surfaces the exact endpoint more cleanly.

---

## 7. Responsible Use

**Where could this system cause real world harm if used carelessly?**  
Think about wrong answers, missing information, or over trusting the LLM.

If developers trust fluent naive answers, they could hard-code the wrong auth flow, env vars, or endpoints. Missing refusals on out-of-scope topics could also hide that the docs never covered something important (security, billing, permissions).

**What instructions would you give real developers who want to use DocuBot safely?**  
Write 2 to 4 short bullet points.

- Prefer RAG or retrieval-only over naive generation for project-specific questions.  
- Treat answers as leads, then open the cited file and verify before shipping.  
- If DocuBot refuses or retrieval looks weak, check the docs yourself instead of forcing an answer.  
- Do not paste secrets into prompts, and do not treat model output as a substitute for code review.

---
