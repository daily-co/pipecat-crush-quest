from google import genai
from google.genai import types
from PIL import Image
from io import BytesIO
import time
from dotenv import load_dotenv

from crushes_for_img import CRUSHES

load_dotenv(override=True)


client = genai.Client()

for crush in CRUSHES:
    p = f"{crush['character']}. You hang out at {crush['location']}. You wear {crush['clothing']}."

    prompt = f"Create a picture, in the style of 1990's magazine collage, of a character with this description: {p}."

    response = client.models.generate_content(
        model="gemini-2.5-flash-image",
        contents=[prompt],
    )

    for part in response.candidates[0].content.parts:
        if part.text is not None:
            print(part.text)
        elif part.inline_data is not None:
            image = Image.open(BytesIO(part.inline_data.data))
            image.save(f"{crush['name']}-{time.time()}.png")
