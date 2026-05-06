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

Bugs fixed:
- Model name corrected from non-existent "gpt-5.4-mini" to "gpt-4.1-mini"
- response_format=json_object requires the model to return a JSON *object*, not a
  bare array. Prompt now instructs the model to return {"tokens": [...]} and the
  parse logic unwraps it. This eliminates the API refusal that occurred when the
  model tried to emit a bare JSON array under json_object mode.
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
Analyze the sentence and return a JSON object with a single key "tokens" whose value
is an array of token objects — one per word, in order.

Each token MUST include:
- "text": the exact word from the sentence

Optional fields (only include if relevant and useful for learners):
- "case": nominative | accusative | dative | genitive
- "gender": masculine | feminine | neuter
- "role": subject | object | verb 

Rules:
- Keep tokens in exact sentence order
- Do NOT merge or skip words
- Only annotate when genuinely useful for learners
- Verbs should have role="verb"
- Subjects should have role="subject" 
- Direct objects → case="acc" (accusative)
- Indirect objects → case="dat" (dativ)
- genetive -> case="gen"
- nominativ -> case="nom"
- gender: (masc,fem,neu)
- verbs are going to be in "bold", that way if we have a trennbare verb, we have both parts in bold. 

Return ONLY a valid JSON object in this exact shape:
{{"tokens": [
  {{"text": "Ich", "role": "subject", "bold": True}},
  {{"text": "gebe", "role": "verb"}},
  {{"text": "dem", "case": "dat", "gender": "masc"}},
  ...
]}}

Sentence:
"{sentence}"
""".strip()


def generate_annotations(sentence: str) -> list[dict]:
    prompt = _build_prompt(sentence)

    logger.info("Calling GPT for annotations on: %r", sentence)

    resp = client.chat.completions.create(
        model="gpt-4.1-mini",           # Fixed: was non-existent "gpt-5.4-mini"
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},   # requires dict → prompt returns {"tokens":[...]}
        temperature=0.2,
    )

    content = resp.choices[0].message.content

    try:
        data = json.loads(content)

        # Primary path: model returns {"tokens": [...]} as instructed
        if isinstance(data, dict) and "tokens" in data:
            return data["tokens"]

        # Fallback: model returned a bare list despite instructions
        if isinstance(data, list):
            logger.warning("Model returned bare list instead of {tokens:[...]} — accepting anyway")
            return data

        # Fallback: model wrapped in some other key
        for key, val in data.items():
            if isinstance(val, list):
                logger.warning("Model returned tokens under key %r — accepting", key)
                return val

        raise ValueError(f"Unexpected JSON structure: {list(data.keys())}")

    except json.JSONDecodeError:
        logger.error("Invalid JSON from model:\n%s", content)
        raise


# 🧪 TEST
if __name__ == "__main__":
    sentence = "Ich gebe dem Mann das Buch"
    tokens = generate_annotations(sentence)
    print(json.dumps(tokens, indent=2, ensure_ascii=False))
