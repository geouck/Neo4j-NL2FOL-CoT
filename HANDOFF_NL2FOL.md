# Handoff: Z3 & Local Ollama Integration
**Date:** April 15, 2026

## What has happened?
The old 11-step LLM pipeline, which was based on CVC5 and multiple text-based prompts, has been completely rebuilt. We have also moved away from the temporary Mistral API architecture.

The method now relies on **Local Models (Ollama)** combined with constrained decoding (JSON schema) and separate AST-based Z3 evaluations.

### Major Architecture:
1. **Local Inference (`src/ollama_nl2fol.py`)**: Uses local reasoning models (`qwen2.5:14b`, `phi4`) instead of external APIs. Uses explicit JSON formatting to avoid skewed text parsing.
2. **Split Generation and Evaluation**: Evaluating the raw FOL is decoupled. `src/z3_evaluator.py` evaluates the generated formulas via Python `ast.parse` and the Z3 solver. This prevents having to rerun heavy LLM inference when debugging logic rules.
3. **End of Regex & CVC5**: We strictly use Z3 evaluated through Python AST nodes. Z3 generates a counter-model when a claim evaluates to `sat` (Fallacy).
4. **Strict First-Order Logic**: We explicitly enforce functional FOL (e.g., `Implies(Exists(...))`) via `prompt_folV2.txt` to prevent Z3 Type mismatch / Higher-Order Logic errors.

### Execution Now:
You can run generation and evaluation separately:
```bash
# 1. Generate FOL representations
python3 src/ollama_nl2fol.py

# 2. Evaluate logic with Z3
python3 src/z3_evaluator.py
```

## Severe Methodological Challenges (Neo4j & the LLM - April 10, 2026)
During testing on the `logicclimate` dataset, we discovered that our previous  Neuro-Symbolic pipeline had serious architectural weaknesses in the coupling between Graph, LLM, and Z3.

**The primary problems are:**
1. **Free and unbounded predicates (Trivial SAT Counter-models):** 
   Neo4j currently just returns lists of `SUBJECT`/`OBJECT` strings. The LLM therefore freely tries to invent logical predicates (e.g., `IsNaturalWarming(x)`). Since the Z3 solver is presented with variables without rules/constraints (Axioms), Z3 will *always* be able to make the implication true by simply setting all predicates to `False` (`[else -> False]`). The system therefore labels almost everything as fallacies without real logical contradiction.
   
2. **Type errors and Higher-Order Logic (Sort Mismatch):** 
   The LLM occasionally generates logic where a predicate is used as an argument in another predicate (e.g., `HasProof(p, Continues(r))`). Python `ast` and `z3-solver` only support First-Order Logic (FOL), which makes our program crash with *Sort mismatch* or *Unsupported BinOp*. The system incorrectly falls back on the result "Valid".

3. **Circular Logic (Tautologies):**
   Without a strict prompt, the LLM often generates structures like A AND NOT B IMPLIES NOT B. This is generally always true according to logical principles, and therefore tests no semantic knowledge in the Z3 setup.


### Legacy Action Plan (Refactoring of Neo4jGraphRAG)
To get the system to evaluate true logical soundness, we need to rewrite `Neo4jGraphRAG.py`:
- **From concepts to graph axioms:** The database should not just return entities, but return triplets/relations `(:Subjekt)-[:RELATION]->(:Objekt)` which are presented to the LLM in a fixed logical format (Axioms).
- **Proof by contradiction ($A \land C$):** The LLM must formulate the Graph's axioms ($A$) and the claim ($C$). Instead of checking a loose implication, the system must test if the formulation is impossible ($A \land C \equiv UNSAT$). If it is UNSAT, the claim is against the graph's truth!
- **Strict Predicate Prompting:** The LLM must be forbidden from generating predicates that are *not* explicitly present in the Graph Axioms.

## April 13, 2026: Next Steps - Local Ollama (qwen2.5:14b & phi4) with Constrained Decoding
After successful testing of the structure and identification of hallucinations from old API calls, we are now seriously switching to a completely local setup! We have installed **Ollama** and downloaded strong local reasoning models like `qwen2.5:14b` and `phi4:latest`.

### Revised Action Plan for Pipeline Upgrade:
1. **Local Inference with Qwen2.5 and Constrained Decoding (Module A & src/ollama_nl2fol.py)**
   - We have switched frameworks and renamed the pipeline file to `src/ollama_nl2fol.py`.
   - The entire interaction now runs against `http://localhost:11434/api/chat`.
   - To solve the problem with "Properties:" prefixes and formatting errors from legacy text-completion prompts, we utilize Ollama's **JSON Schema (format)**. We are redesigning the methods (`extract_claim_and_implication`, `get_properties`, `get_fol`) to return strict JSON instead of parsing skewed text.

2. **Recreation of the SMT path (Module B)**
   - We continue running `fol_to_cvc.py` (CVC4/CVC5) with the clean logic strings generated under point 1 to catch satisfiability.

3. **Implementation of NL2FOL Module C (Classification & Explanation)**
   - We have confirmed that the original paper does not stop at the `cvc4` validation (where `sat` = Logically Fallacious).
   - When the solver computes a fallacy (`sat`), it generates a **counter-model**.
   - We need to build **Module C**: A prompt against `qwen2.5:14b` that takes the fallacy's *claim*, *FOL formula* AND *SMT counter-model* to (1) generate a human explanation for the error, and (2) classify the final fallacy type based on the 13 fallacy categories in the dataset.

## April 13, 2026: Architecture Decision - Keeping Generation and Evaluation Separate (For Now)
During testing of the new AST-based pipeline with Z3, we successfully ran intermediate evaluations and encountered a few syntax/sort mismatch errors (e.g. `Sort mismatch` for formulas 2 and 7). 

**Current Decision: Keep `ollama_nl2fol.py` and `z3_evaluator.py` as separate scripts.**
* **Why?** Generating the FOL AST representations via the LLM (`qwen2.5:14b`) takes a significant amount of time. Keeping `z3_evaluator.py` separate allows us to instantly hot-reload and debug the Z3 constraints (like the `Sort mismatch` errors) against the static `.csv` outputs without needing to rerun the heavy LLM generation on every tweak. It also preserves the intermediate CSVs for manual inspection of the ASTs.
* **Future Work:** Once the Z3 evaluation logic is 100% stable and error-free on all valid AST types, this should be refactored into a single end-to-end orchestrated pipeline (`run_pipeline.py`) that executes generation and evaluation sequentially in one call.

## April 13, 2026: Fixing Z3 "Sort Mismatch" (No Higher-Order Logic)
During testing of the AST-based pipeline, the script successfully hit Z3 without regex crashes, but occasionally encountered a `Z3 Evaluation Error: Sort mismatch` on nested formulas like `Recommends(a, Needs(c, b))`.
* **The Bug:** The LLM was implicitly generating **Higher-Order Logic**. It took a predicate (like `Needs`) and passed it as an argument inside *another* predicate (like `Recommends`). Z3 and First-Order Logic strictly forbid nesting predicates (arguments must be purely Entities/Sorts, not Booleans).
* **The Fix:** We updated the `prompt_fol.txt` with an explicit anti-nesting rule: *CRITICAL: Do NOT use Higher-Order Logic. Predicates cannot be passed as arguments inside other predicates.*
* **Strategy Path:** The LLM is now forced to flatten multi-action relationships into independent Boolean states connected by logical conjunctions (`And(...)`), completely matching the original methodology of the paper and strictly passing the mathematical bounds of Z3.

## April 13, 2026: Next Steps (Mismatched Brackets & Hanging XAI)
During our final evaluation run, we successfully confirmed that the `Sort mismatch` error is completely eliminated! The prompt constraint successfully forced the LLM to output flattened First-Order Logic (e.g., `Implies(Exists(a...) And(...))`).

However, we encountered two new minor issues to solve next time:
1. **Mismatched Brackets SyntaxError:** Because the prompt constraints on Qwen 14b became quite strict, it occasionally generated unmatched brackets (e.g., `Implies([IsHigher(b,a), [FacesClimateChangeIssues(c)))`) on the most complex logic expressions.
   - *Solution options to try next:* We can try to make the prompt instruction more concise so it doesn't confuse the smaller model, apply a simple python regex string-cleaner to replace `[` with `(` before hitting `ast.parse()`, or try a slightly larger model.
2. **Hanging XAI API Calls:** When the `z3_evaluator.py` finds a counter-model, it attempts to call an LLM endpoint for an "XAI explanation". This API call is currently hanging/timing out.
   - *Solution options to try next:* Temporarily comment out or add a toggle flag to bypass the XAI explanation generation in `src/z3_evaluator.py` so we can benchmark the pure logical pipeline smoothly.


## To-Do / Next Steps
- **Prompt Testing:** Test the newly drafted `prompt_folV2.txt` in the generation pipeline to see if it reduces Z3 evaluation errors (e.g. syntax errors like unmatched parentheses and invalid quantifiers) compared to the original `prompt_fol.txt`.

### Known Z3 Evaluation Edge Cases to Fix
1. **Malformed Boolean Expressions**: The LLM sometimes outputs `True` as a consequent (e.g. `Implies(..., True)`). Z3 expects predicates, not constants, which raises `Value cannot be converted into a Z3 Boolean value`. *Fix*: Add logic to replace `True` with a tautology or instruct the prompt.
2. **Unmatched Parentheses**: Deeply nested quantifiers cause the LLM to drop/add parentheses, causing `unmatched ')'` or `'(' was never closed`. *Fix*: Implement a basic AST/parenthesis validation check before passing.
3. **Variable Shadowing**: The LLM reuses variables in nested scopes (e.g., `Exists(a, ForAll(a, ...))`), which can break standard FOL solver logic. *Fix*: Post-process to ensure uniquely bound variables or strictly enforce it in the prompt.
