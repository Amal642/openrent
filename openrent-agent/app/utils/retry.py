import asyncio

from app.utils.logger import logger


async def retry_async(

    func,

    retries=3,

    delay=2,

    retry_name="operation"
):

    last_error = None

    for attempt in range(
        1,
        retries + 1
    ):

        try:

            return await func()

        except Exception as e:

            last_error = e

            logger.warning(

                f"{retry_name} failed "
                f"(attempt {attempt}/{retries}) "
                f"- {e}"
            )

            await asyncio.sleep(delay)

    logger.exception(
        f"{retry_name} failed permanently"
    )

    raise last_error