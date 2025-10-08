import random
from datetime import datetime
from zlib import adler32

import pytz
from loguru import logger

from crush_utils.crushes import CRUSHES


def get_now_central_time():
    # Get Central US Time (best time zone)
    central = pytz.timezone("US/Central")
    now_central = datetime.now(central)
    logger.debug(f"_____bot.py * timezone now_central: {now_central}")
    return now_central


def get_crush_index(phone_number: str, dt: datetime) -> int:
    # Hash the phone number + current date to get a stable index
    idx = adler32((str(phone_number) + str(dt.date())).encode()) % len(CRUSHES)
    logger.info(f"_____bot.py * get_crush_index str(phone_number): {str(phone_number)}")
    logger.info(f"_____bot.py * get_crush_index str(dt.date()): {str(dt.date())}")
    logger.info(f"_____bot.py * get_crush_index idx: {idx}")
    logger.debug(
        f"________** crush_idx: {idx}; YOUR CRUSH IS: {CRUSHES[idx]['name']}"
    )

    return idx


def get_clue_giver_index(to_number):
    clue_giver_idx = [i for i, c in enumerate(CRUSHES) if c["number"] == to_number][0]
    clue_giver = CRUSHES[clue_giver_idx]
    logger.debug(
        f"________** clue_giver_idx: {clue_giver_idx}; YOUR CLUE GIVER IS: {CRUSHES[clue_giver_idx]['name']}"
    )
    return [clue_giver_idx, clue_giver]


def get_clue(crush_idx: int, phone_number: str, dt: datetime, clue_giver_idx: int) -> str:
    """Assign each potential crush a clue based on the current date and the phone number dialing in."""
    crush = CRUSHES[crush_idx]
    # Get all possible options for each attribute, remove the current crush's value and sort to get a consistent order

    locations = sorted(
        [
            f"I know where they hang out – they're not at {l}"
            for l in set([c["location"] for c in CRUSHES if c["location"] != crush["location"]])
        ]
    )
    food = sorted(
        [
            f"They'll eat almost anything, except {f}"
            for f in set(
                c["food"]
                for c in CRUSHES
                if c.get("food") is not None and c["food"] != crush.get("food", "NA")
            )
        ]
    )
    sport = sorted(
        [
            f"They like most sports, but not {s}"
            for s in set(
                c["sport"]
                for c in CRUSHES
                if c.get("sport") is not None and c["sport"] != crush.get("sport", "NA")
            )
        ]
    )
    clothing = sorted(
        [
            f"They look cool in whatever they wear – they're not wearing {c}"
            for c in set(c["clothing"] for c in CRUSHES if c["clothing"] != crush["clothing"])
        ]
    )

    # Should total up to 12 clues, so one for each potential crush
    clues = locations + food + sport + clothing + ["Haaaa-haaa! I'm not telling"]
    logger.debug(f"__before___bot.py * clues: {clues}")

    # Deterministic shuffle using a hash of the phone number and date
    random.Random(adler32((str(phone_number) + str(dt.date())).encode())).shuffle(clues)
    logger.debug(f"__after___bot.py * clues: {clues}")

    clue_ret = clues[clue_giver_idx]
    logger.debug(f"________** YOUR CLUE: {clue_ret}")
    return clue_ret
