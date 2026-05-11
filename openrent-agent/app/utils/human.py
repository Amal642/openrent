import asyncio
import random


async def random_sleep(
    minimum=1,
    maximum=3
):

    seconds = random.uniform(
        minimum,
        maximum
    )

    print(
        f"Sleeping {seconds:.2f}s"
    )

    await asyncio.sleep(seconds)