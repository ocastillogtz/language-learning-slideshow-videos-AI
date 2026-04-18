"""
generate_annotations.py
======================

Generates grammar annotations for a German sentence using GPT.

Output format:
[
  {
    "text": "dem",
    "case": "dative",
    "gender": "masculine"
  }
]
"""

import json
import logging
import os

from dotenv import load_dotenv
from openai import OpenAI

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def _build_prompt(sentence: str) -> str:
    return f"""
You are a German grammar annotator.

Task:
Analyze the sentence and return a JSON array of tokens.

Each token MUST include:
- "text": the exact word from the sentence

Optional fields (only include if relevant):
- "case": nominative | accusative | dative | genitive
- "gender": masculine | feminine | neuter
- "role": subject | object | verb

Rules:
- Keep tokens in exact order
- Do NOT merge words
- Do NOT invent words
- Only annotate when useful for learners
- Verbs should have role="verb"
- Subjects should have role="subject"
- Direct objects → accusative
- Indirect objects → dative

Return ONLY valid JSON (no markdown, no explanations)

Sentence:
"{sentence}"
""".strip()


def generate_annotations(sentence: str) -> list[dict]:
    prompt = _build_prompt(sentence)

    logger.info("Calling GPT for annotations…")

    resp = client.chat.completions.create(
        model="gpt-5.4-mini",
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        temperature=0.2,
    )

    content = resp.choices[0].message.content

    try:
        data = json.loads(content)

        # allow either { "tokens": [...] } or raw list
        if isinstance(data, dict) and "tokens" in data:
            return data["tokens"]
        elif isinstance(data, list):
            return data
        else:
            raise ValueError("Unexpected JSON structure")

    except json.JSONDecodeError:
        logger.error("Invalid JSON from model:\n%s", content)
        raise


# 🧪 TEST
if __name__ == "__main__":
    sentence = "Ich gebe dem Mann das Buch"
    tokens = generate_annotations(sentence)

    print(json.dumps(tokens, indent=2, ensure_ascii=False))