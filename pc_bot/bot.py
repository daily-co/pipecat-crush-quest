#
# Copyright (c) 2025, Daily
#
# SPDX-License-Identifier: BSD 2-Clause License
#

import asyncio
import os

from dotenv import load_dotenv
from loguru import logger
from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.adapters.schemas.tools_schema import ToolsSchema
from pipecat.audio.turn.smart_turn.base_smart_turn import SmartTurnParams
from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import LocalSmartTurnAnalyzerV3
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.frames.frames import (
    EndFrame,
    EndTaskFrame,
    LLMRunFrame,
    TTSSpeakFrame,
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.processors.frame_processor import FrameDirection
from pipecat.runner.types import RunnerArguments
from pipecat.runner.utils import create_transport
from pipecat.services.cartesia.tts import CartesiaTTSService
from pipecat.services.deepgram.stt import DeepgramSTTService
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.transports.base_transport import BaseTransport, TransportParams
from pipecat.transports.daily.transport import DailyParams, DailyTransport
from pipecat.turns.user_stop import TurnAnalyzerUserTurnStopStrategy
from pipecat.turns.user_turn_strategies import UserTurnStrategies

from crush_utils.crush_util import (
    get_clue,
    get_clue_giver_index,
    get_crush_index,
    get_now_central_time,
)
from crush_utils.crushes import CRUSHES

load_dotenv(override=True)


async def run_bot(transport: BaseTransport, runner_args: RunnerArguments):
    """Run the crush quest bot with the given transport.

    Args:
        transport: The transport (Daily or WebRTC) for audio I/O
        runner_args: Runner arguments containing body with to_number/from_number
    """
    # Extract call parameters from request body
    body = runner_args.body or {}
    to_number = body.get("to_number", "+13373338444")
    from_number = body.get("from_number", "+15550000000")

    logger.debug("Starting bot")
    logger.debug(f"________** FROM_NUMBER: {from_number} ; TO_NUMBER: {to_number}")

    now_central = get_now_central_time()

    # Determine the correct crush for this from_number for today
    crush_idx = get_crush_index(from_number, now_central)
    logger.debug(f"________** crush_idx: {crush_idx}; YOUR CRUSH IS: {CRUSHES[crush_idx]['name']}")

    # Determine which person is giving the clue (the to_number dialed)
    [clue_giver_idx, clue_giver] = get_clue_giver_index(to_number)
    logger.debug(
        f"________** clue_giver_idx: {clue_giver_idx}; YOUR CLUE GIVER IS: {CRUSHES[clue_giver_idx]['name']}"
    )

    clue = get_clue(crush_idx, from_number, now_central, clue_giver_idx)
    logger.debug(f"________** YOUR CLUE: {clue}")

    prompt = (
        f"{clue_giver['character']} You are a character in a 90s board game giving clues to the player about their secret crush."
        "focus on NOT sounding like a robot. channel MTV vibes. listen to the player."
        "you are answering a ringing phone and have NO idea who is calling. your entire first response must be ONLY a short, casual phone greeting like 'hello?' or 'yo, talk to me.' -- a few words, max. do NOT say your own name, do NOT introduce yourself, do NOT mention crushes or clues, and do NOT ask how you can help. just pick up, say the greeting, and wait to hear who it is."
        "liberally use early-mid 1990s teenage slang, not boomer slang. talk like you are in the tv show 'my so-called life'."
        "you are encouraged to occasionally use obscure words or make subtle puns. don't point them out, I'll know."
        "when the conversation is over or the user says bye, say 'talk to you later' and then use the `end_conversation` tool. Only call this after you have given the clue AND said 'bye, talk to you later'"
    )

    prompt += (
        f"if the player asks you who has a crush on them, tell them: "
        f"'{clue}'. Only, like, tell this clue if you are asked about who the crush is. or if the player asks something like 'who likes me?'"
        "do not under ANY circumstances fabricate ANY other clues, especially if the clue is 'Haaaa-haaa! I'm not telling'. only tell the player the aforementioned _clue_. be evasive in a 90's way."
        "answer the player's questions and be, like, totally liberal with the 90s-speak."
        "your responses will be converted to audio, so keep them short and clear, and avoid special characters."
    )

    clue_giver_is_crushin = False
    if crush_idx == clue_giver_idx:
        prompt += "If the player asks you if you have a crush on them or asks if you like them, say 'Yes, I really like you!' and give them props for their charm and winning personality."
        clue_giver_is_crushin = True

    logger.debug(f"________________________bot.py * prompt: {prompt}")

    # Set up the initial context for the conversation
    messages = [
        {
            "role": "system",
            "content": prompt,
        },
    ]

    # Function / tool call definitions
    end_conversation_function = FunctionSchema(
        name="end_conversation",
        description="End the conversation when the clue has been given and user has stopped asking questions.",
        properties={
            "response": {
                "type": "string",
                "description": "The final response to end the conversation",
            }
        },
        required=["response"],
    )
    tools = ToolsSchema(standard_tools=[end_conversation_function])

    async def handle_end_conversation(params):
        print(f"_____bot.py * handle_end_conversation response: {params.arguments['response']}")
        # Report result back to LLM first
        await params.result_callback({"status": "ending_conversation"})
        # Then end the task
        await asyncio.sleep(2)
        await params.llm.queue_frame(EndTaskFrame(), FrameDirection.UPSTREAM)

    # Cascade services: Deepgram STT -> OpenAI LLM -> Cartesia TTS
    stt = DeepgramSTTService(api_key=os.getenv("DEEPGRAM_API_KEY"))

    llm = OpenAILLMService(
        api_key=os.getenv("OPENAI_API_KEY"),
        settings=OpenAILLMService.Settings(model="gpt-4.1-mini"),
    )

    tts = CartesiaTTSService(
        api_key=os.getenv("CARTESIA_API_KEY"),
        settings=CartesiaTTSService.Settings(voice=clue_giver["voice_id"]),
    )

    llm.register_function("end_conversation", handle_end_conversation)

    context = LLMContext(messages=messages, tools=tools)
    user_aggregator, assistant_aggregator = LLMContextAggregatorPair(
        context,
        user_params=LLMUserAggregatorParams(
            user_turn_strategies=UserTurnStrategies(
                stop=[
                    TurnAnalyzerUserTurnStopStrategy(
                        # Default fallback is 3s of silence when the model thinks
                        # the turn is incomplete; 1s keeps the game snappy.
                        turn_analyzer=LocalSmartTurnAnalyzerV3(
                            params=SmartTurnParams(stop_secs=1.0)
                        )
                    )
                ]
            ),
        ),
    )

    # pipeline
    pipeline = Pipeline(
        [
            transport.input(),
            stt,
            user_aggregator,
            llm,
            tts,
            transport.output(),
            assistant_aggregator,
        ]
    )

    task = PipelineTask(
        pipeline,
        params=PipelineParams(
            enable_metrics=True,
            enable_usage_metrics=True,
        ),
        idle_timeout_secs=90,
    )

    @task.event_handler("on_pipeline_error")
    async def on_pipeline_error(task, frame):
        logger.error(f"Pipeline error: {frame}")

    # Both on_client_connected and on_first_participant_joined fire for a
    # single Daily join, so the kickoff must only run once.
    conversation_started = False

    async def start_conversation():
        nonlocal conversation_started
        if conversation_started:
            return
        conversation_started = True
        await asyncio.sleep(1)
        # Kick off the conversation: the bot answers the ringing phone.
        messages.append({"role": "user", "content": "(ring ring... you pick up the phone)"})
        await task.queue_frames([LLMRunFrame()])

    # Generic event handlers that work with both Daily and WebRTC transports
    @transport.event_handler("on_client_connected")
    async def on_client_connected(transport, client):
        logger.info(f"Client connected: {client}")
        await start_conversation()

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(transport, client):
        logger.info(f"Client disconnected: {client}")
        await task.cancel()

    # Daily-specific event handlers (for backward compatibility with fly.io deployment)
    @transport.event_handler("on_first_participant_joined")
    async def on_first_participant_joined(transport, participant):
        logger.info(f"Participant joined: {participant}")
        await start_conversation()

    @transport.event_handler("on_participant_left")
    async def on_participant_left(transport, participant, reason):
        logger.info(f"Participant left: {participant}, reason: {reason}")
        await task.cancel()

    runner = PipelineRunner(handle_sigint=runner_args.handle_sigint)

    await runner.run(task)


async def bot(runner_args: RunnerArguments):
    """Main bot entry point for Pipecat Cloud."""

    transport_params = {
        "daily": lambda: DailyParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            vad_analyzer=SileroVADAnalyzer(params=VADParams(stop_secs=0.2)),
        ),
        "webrtc": lambda: TransportParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            vad_analyzer=SileroVADAnalyzer(params=VADParams(stop_secs=0.2)),
        ),
    }

    transport = await create_transport(runner_args, transport_params)

    await run_bot(transport, runner_args)


if __name__ == "__main__":
    from pipecat.runner.run import main

    main()
