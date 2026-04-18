from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont


ROOT = Path("data/test-assets")
CANVAS = (1400, 1000)
BODY_FONT = "/System/Library/Fonts/Supplemental/Arial.ttf"
BOLD_FONT = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"


def main() -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    fonts = {
        "title": ImageFont.truetype(BOLD_FONT, 50),
        "subtitle": ImageFont.truetype(BODY_FONT, 30),
        "body": ImageFont.truetype(BODY_FONT, 34),
        "body_bold": ImageFont.truetype(BOLD_FONT, 34),
        "small": ImageFont.truetype(BODY_FONT, 26),
        "small_bold": ImageFont.truetype(BOLD_FONT, 26),
    }

    scenarios = [
        build_supply_board(fonts),
        build_whiteboard_plan(fonts),
        build_market_receipt(fonts),
        build_clinic_triage_card(fonts),
    ]

    manifest = []
    for scenario in scenarios:
        image_path = ROOT / scenario["file_name"]
        scenario["image"].save(image_path, format="PNG")
        manifest.append(
            {
                "file_name": scenario["file_name"],
                "title": scenario["title"],
                "care_context": scenario["care_context"],
                "suggested_prompts": scenario["suggested_prompts"],
                "follow_up_prompts": scenario["follow_up_prompts"],
                "task_prompts": scenario["task_prompts"],
            }
        )

    (ROOT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))


def build_supply_board(fonts: dict[str, ImageFont.FreeTypeFont]) -> dict[str, object]:
    image = Image.new("RGB", CANVAS, "#d8cdb8")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((70, 70, 1320, 920), radius=36, fill="#2b3d2f")
    draw.text((120, 120), "Village Visit Supply Board", fill="#f7f0df", font=fonts["title"])
    draw.text((120, 185), "Before departure at 7:30 PM", fill="#c7d3c4", font=fonts["subtitle"])

    items = [
        ("ORS packets", "18", "#7dd17d"),
        ("Water tablets", "9", "#f2b544"),
        ("Latex gloves", "2 boxes", "#f2b544"),
        ("Lantern batteries", "LOW", "#ff8a66"),
        ("Consent forms", "42", "#7dd17d"),
        ("Translator phone credits", "NEEDS TOP-UP", "#ff8a66"),
    ]
    y = 250
    for label, value, accent in items:
        draw.rounded_rectangle((110, y - 10, 1280, y + 70), radius=22, fill="#f0eadb")
        draw.text((150, y + 10), label, fill="#1f261d", font=fonts["body"])
        draw.rounded_rectangle((990, y + 8, 1240, y + 52), radius=16, fill=accent)
        draw.text((1030, y + 16), value, fill="#111111", font=fonts["body_bold"])
        y += 105

    draw.rounded_rectangle((110, 830, 1280, 885), radius=18, fill="#f2b544")
    draw.text(
        (145, 850),
        "Action note: Buy batteries and top up translator credit before leaving base.",
        fill="#1f1406",
        font=fonts["small_bold"],
    )
    return {
        "title": "Village Visit Supply Board",
        "file_name": "field_supply_board.png",
        "care_context": "general",
        "image": image.filter(ImageFilter.GaussianBlur(radius=0.2)),
        "suggested_prompts": [
            "Summarize the visible supply situation.",
            "What items look low or urgent?",
        ],
        "follow_up_prompts": [
            "Which two items should we prioritize before departure?",
            "Quote the action note in your own words.",
        ],
        "task_prompts": [
            "Create a checklist for the shortages shown in this board.",
            "Create a task to restock the urgent items from this image.",
        ],
    }


def build_whiteboard_plan(fonts: dict[str, ImageFont.FreeTypeFont]) -> dict[str, object]:
    image = Image.new("RGB", CANVAS, "#efefea")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((120, 90, 1280, 910), radius=28, fill="#fafcff", outline="#ccd6dd", width=10)
    draw.text((180, 145), "Tuesday Field Route", fill="#1a4059", font=fonts["title"])
    draw.text((180, 215), "Team: Ruth, Samuel, Mariam", fill="#426578", font=fonts["subtitle"])

    rows = [
        "08:00  Load water filter demo kits",
        "09:15  Meet translator at Mako junction",
        "10:00  School hygiene lesson in Kati village",
        "12:30  Lunch and battery swap",
        "14:00  Household follow-up visits",
        "17:30  Debrief and inventory count",
    ]
    y = 280
    for row in rows:
        draw.text((200, y), row, fill="#10222e", font=fonts["body"])
        draw.line((180, y + 42, 1220, y + 42), fill="#d4dde5", width=3)
        y += 95

    draw.rounded_rectangle((170, 760, 1230, 855), radius=20, fill="#1a4059")
    draw.text(
        (210, 792),
        "Reminder: pick up cooler ice packs and print 12 debrief sheets.",
        fill="#f5f8fa",
        font=fonts["small_bold"],
    )
    return {
        "title": "Tuesday Field Route Whiteboard",
        "file_name": "community_whiteboard_plan.png",
        "care_context": "general",
        "image": image.rotate(-2, expand=False, fillcolor="#efefea"),
        "suggested_prompts": [
            "Summarize the schedule shown here.",
            "What are the key stops and reminders?",
        ],
        "follow_up_prompts": [
            "What happens before the school lesson?",
            "What needs to be picked up later in the day?",
        ],
        "task_prompts": [
            "Create a checklist from this whiteboard plan.",
            "Create a task for the reminder items on the board.",
        ],
    }


def build_market_receipt(fonts: dict[str, ImageFont.FreeTypeFont]) -> dict[str, object]:
    image = Image.new("RGB", CANVAS, "#b7a186")
    paper = Image.new("RGB", (760, 900), "#fffdfa")
    paper_draw = ImageDraw.Draw(paper)
    paper_draw.text((75, 60), "Mako General Market", fill="#2a1f16", font=fonts["body_bold"])
    paper_draw.text((75, 115), "17 Apr 2026  18:42", fill="#6a5d52", font=fonts["small"])
    paper_draw.text((75, 155), "Cashier: L. Traore", fill="#6a5d52", font=fonts["small"])

    line_items = [
        ("Lantern batteries", "2", "18.00"),
        ("Phone credit top-up", "1", "12.50"),
        ("Printed debrief sheets", "12", "9.00"),
        ("Water tablets", "3", "15.75"),
    ]
    y = 245
    for item, qty, price in line_items:
        paper_draw.text((85, y), item, fill="#1f1914", font=fonts["body"])
        paper_draw.text((520, y), qty, fill="#1f1914", font=fonts["body"])
        paper_draw.text((615, y), price, fill="#1f1914", font=fonts["body"])
        y += 82

    paper_draw.line((80, 590, 680, 590), fill="#b8afa7", width=3)
    paper_draw.text((90, 635), "Subtotal", fill="#2a1f16", font=fonts["body"])
    paper_draw.text((575, 635), "55.25", fill="#2a1f16", font=fonts["body"])
    paper_draw.text((90, 690), "Transport fee", fill="#2a1f16", font=fonts["body"])
    paper_draw.text((590, 690), "3.00", fill="#2a1f16", font=fonts["body"])
    paper_draw.text((90, 770), "TOTAL", fill="#1a4059", font=fonts["body_bold"])
    paper_draw.text((560, 770), "58.25", fill="#1a4059", font=fonts["body_bold"])

    rotated = paper.rotate(6, expand=True, fillcolor="#b7a186")
    image.paste(rotated, (290, 55))
    image = image.filter(ImageFilter.GaussianBlur(radius=0.35))
    return {
        "title": "Mission Market Receipt",
        "file_name": "mission_market_receipt.png",
        "care_context": "general",
        "image": image,
        "suggested_prompts": [
            "Extract the visible items and total from this receipt.",
            "Summarize the expenses shown.",
        ],
        "follow_up_prompts": [
            "Which purchase looks related to the translator reminder?",
            "What is the final total including the fee?",
        ],
        "task_prompts": [
            "Create a note summarizing the purchases from this receipt.",
            "Create a task to reimburse the market expenses shown here.",
        ],
    }


def build_clinic_triage_card(fonts: dict[str, ImageFont.FreeTypeFont]) -> dict[str, object]:
    image = Image.new("RGB", CANVAS, "#dde7ef")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((150, 90, 1240, 900), radius=30, fill="#ffffff")
    draw.rounded_rectangle((150, 90, 1240, 180), radius=30, fill="#9a2d2d")
    draw.text((210, 118), "Remote Clinic Triage Card", fill="#fff7f5", font=fonts["title"])
    draw.text((210, 220), "Name: Amina K.", fill="#17212a", font=fonts["body"])
    draw.text((210, 280), "Age: 7", fill="#17212a", font=fonts["body"])
    draw.text((210, 340), "Complaint: fever and cough for 4 days", fill="#17212a", font=fonts["body"])
    draw.text((210, 425), "Temp: 38.4 C", fill="#17212a", font=fonts["body"])
    draw.text((210, 485), "Pulse: 112", fill="#17212a", font=fonts["body"])
    draw.text((210, 545), "SpO2: 91%", fill="#17212a", font=fonts["body"])
    draw.text((210, 605), "Breathing: labored at night", fill="#17212a", font=fonts["body"])
    draw.rounded_rectangle((190, 625, 1200, 745), radius=20, fill="#fff0eb", outline="#d9624e", width=4)
    draw.text(
        (225, 665),
        "Escalation note: Needs clinician review and chest exam today.",
        fill="#7a241c",
        font=fonts["small_bold"],
    )
    draw.text(
        (210, 805),
        "Field note: Mother reports reduced appetite and poor sleep.",
        fill="#334551",
        font=fonts["small"],
    )
    return {
        "title": "Clinic Triage Card",
        "file_name": "clinic_triage_card.png",
        "care_context": "medical",
        "image": image,
        "suggested_prompts": [
            "Summarize the visible medical information conservatively.",
            "What escalation note is visible on this card?",
        ],
        "follow_up_prompts": [
            "What are the vitals shown?",
            "What details should be carried into a clinician handoff?",
        ],
        "task_prompts": [
            "Create a medical case summary task based on the visible card details.",
            "Create a note with the visible triage details for clinician handoff.",
        ],
    }


if __name__ == "__main__":
    main()
