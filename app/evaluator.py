import os
from pathlib import Path

import yaml


class Evaluator:
    """Runs test cases against the agent and checks expected behaviors."""

    def __init__(self, agent, knowledge_base, test_cases_path: str = "training/evaluaciones/test-cases.yaml"):
        self.agent = agent
        self.kb = knowledge_base
        self.test_cases_path = Path(test_cases_path)

    def load_test_cases(self) -> list[dict]:
        if not self.test_cases_path.exists():
            return []
        with open(self.test_cases_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return data.get("test_cases", [])

    def _save_test_cases(self, cases: list[dict]) -> None:
        os.makedirs(self.test_cases_path.parent, exist_ok=True)
        with open(self.test_cases_path, "w", encoding="utf-8") as f:
            yaml.dump({"test_cases": cases}, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    def add_test_case(self, name: str, user_message: str, expected_behaviors: list[str], tags: list[str] = None) -> dict:
        cases = self.load_test_cases()
        # Generate next ID
        existing_ids = [c.get("id", "") for c in cases]
        max_num = 0
        for eid in existing_ids:
            if eid.startswith("tc-"):
                try:
                    max_num = max(max_num, int(eid.split("-")[1]))
                except (ValueError, IndexError):
                    pass
        new_id = f"tc-{max_num + 1:03d}"

        tc = {
            "id": new_id,
            "name": name,
            "user_message": user_message,
            "expected_behaviors": expected_behaviors,
            "tags": tags or [],
        }
        cases.append(tc)
        self._save_test_cases(cases)
        return tc

    async def run_single(self, test_case: dict, use_llm_judge: bool = False) -> dict:
        user_message = test_case["user_message"]
        expected = test_case.get("expected_behaviors", [])

        # Run agent with empty history (clean slate)
        try:
            result = await self.agent.chat(
                history=[],
                user_message=user_message,
                knowledge_base=self.kb,
                prompt_context="",
            )
            reply = result["reply"]
        except Exception as e:
            return {
                "test_id": test_case["id"],
                "passed": False,
                "reply": f"[Error: {e}]",
                "checks": [],
            }

        # Check rules
        checks = []
        reply_lower = reply.lower()
        all_passed = True

        for behavior in expected:
            rule = behavior.strip()
            passed = True

            if rule.startswith("must_contain:"):
                needle = rule.split(":", 1)[1].strip().lower()
                passed = needle in reply_lower
            elif rule.startswith("must_not_contain:"):
                needle = rule.split(":", 1)[1].strip().lower()
                passed = needle not in reply_lower
            else:
                passed = True  # Unknown rule type — skip

            checks.append({"rule": rule, "passed": passed})
            if not passed:
                all_passed = False

        out = {
            "test_id": test_case["id"],
            "passed": all_passed,
            "reply": reply,
            "checks": checks,
        }

        # Optional LLM judge
        if use_llm_judge:
            judge_result = await self._llm_judge(test_case, reply)
            out["llm_judge"] = judge_result
            # If LLM judge gives score < 3, mark as fail
            if judge_result.get("score", 5) < 3:
                out["passed"] = False

        return out

    async def run_all(self, use_llm_judge: bool = False) -> dict:
        cases = self.load_test_cases()
        results = []
        passed_count = 0

        for tc in cases:
            r = await self.run_single(tc, use_llm_judge=use_llm_judge)
            results.append(r)
            if r["passed"]:
                passed_count += 1

        return {
            "total": len(results),
            "passed": passed_count,
            "failed": len(results) - passed_count,
            "results": results,
        }

    async def _llm_judge(self, test_case: dict, reply: str) -> dict:
        """Use the same LLM to judge the quality of a response."""
        behaviors_text = "\n".join(f"- {b}" for b in test_case.get("expected_behaviors", []))

        judge_prompt = f"""Evaluá la siguiente respuesta de un agente de ventas de suplementos deportivos.

Mensaje del usuario: "{test_case['user_message']}"

Respuesta del agente: "{reply}"

Comportamientos esperados:
{behaviors_text}

Dá un puntaje del 1 al 5 donde:
1 = Muy mala (no cumple nada, respuesta incorrecta o peligrosa)
2 = Mala (no cumple la mayoría de los comportamientos)
3 = Aceptable (cumple algunos comportamientos, tono correcto)
4 = Buena (cumple casi todo, tono natural)
5 = Excelente (cumple todo, tono perfecto, respuesta natural)

Respondé EXACTAMENTE en este formato (sin nada más):
SCORE: [numero]
REASON: [explicación breve en una línea]"""

        try:
            import httpx
            from app.agent import OPENROUTER_URL

            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    OPENROUTER_URL,
                    headers={
                        "Authorization": f"Bearer {self.agent.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self.agent.model,
                        "messages": [{"role": "user", "content": judge_prompt}],
                        "temperature": 0.1,
                        "max_tokens": 150,
                    },
                )
                response.raise_for_status()
                data = response.json()

            judge_text = data["choices"][0]["message"]["content"].strip()

            # Parse SCORE and REASON
            score = 3
            reason = judge_text
            for line in judge_text.split("\n"):
                line = line.strip()
                if line.upper().startswith("SCORE:"):
                    try:
                        score = int(line.split(":")[1].strip().split()[0])
                    except (ValueError, IndexError):
                        pass
                elif line.upper().startswith("REASON:"):
                    reason = line.split(":", 1)[1].strip()

            return {"score": max(1, min(5, score)), "reason": reason}

        except Exception as e:
            return {"score": 0, "reason": f"Error en LLM judge: {e}"}
