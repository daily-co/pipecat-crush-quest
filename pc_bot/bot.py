#
# Copyright (c) 2025, Daily
#
# SPDX-License-Identifier: BSD 2-Clause License
#

import asyncio
import json
import os
from datetime import datetime
from typing import Optional

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
    LLMMessagesAppendFrame,
    TTSSpeakFrame,
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.frame_processor import FrameDirection
from pipecat.runner.types import RunnerArguments
from pipecat.runner.utils import create_transport, parse_telephony_websocket
from pipecat.serializers.twilio import TwilioFrameSerializer
from pipecat.services.google.gemini_live.llm import (
    GeminiLiveContext,
    GeminiLiveLLMService,
    HttpOptions,
    InputParams,
    ProactivityConfig,
)
from pipecat.services.google.tts import GoogleTTSService
from pipecat.transcriptions.language import Language
from pipecat.transports.base_transport import BaseTransport, TransportParams
from pipecat.transports.websocket.fastapi import (
    FastAPIWebsocketParams,
    FastAPIWebsocketTransport,
)

from crush_utils.crush_util import (
    get_clue,
    get_clue_giver_index,
    get_crush_index,
    get_now_central_time,
)
from crush_utils.crushes import CRUSHES

load_dotenv(override=True)


async def run_bot(transport: BaseTransport, runner_args: RunnerArguments):
    # async def main(ws: WebSocket):
    logger.debug("Starting WebSocket bot")

    # prod
    try:
        to_number = runner_args.body["to_number"]
        from_number = runner_args.body["from_number"]
    except:
        pass

    # local dev
    try:
        to_number = runner_args["body"]["to_number"]
        from_number = runner_args["body"]["from_number"]
    except:
        pass

    logger.debug(f"________** FROM_NUMBER: {from_number} ; TO_NUMBER: {to_number}")

    now_central = get_now_central_time()

    # Determine the correct crush for this from_number for today
    crush_idx = get_crush_index(from_number, now_central)
    logger.debug(
        f"________** crush_idx: {crush_idx}; YOUR CRUSH IS: {CRUSHES[crush_idx]['name']}"
    )

    # Determine which person is giving the clue (the to_number dialed)
    [clue_giver_idx, clue_giver] = get_clue_giver_index(to_number)
    logger.debug(
        f"________** clue_giver_idx: {clue_giver_idx}; YOUR CLUE GIVER IS: {CRUSHES[clue_giver_idx]['name']}"
    )

    clue = get_clue(crush_idx, from_number, now_central, clue_giver_idx)
    logger.debug(f"________** YOUR CLUE: {clue}")

    prompt = (
        f"{clue_giver['character']} You are a character in a 90s board game giving clues to the player about their secret crush."
        "focus on NOT sounding like a robot. listen to the player."
        "always start the conversation like you are answering the call of a player. Say 'hello?' or another typical, short phone greeting (with 90's style). Wait for the player to respond."
        "liberally use early-mid 1990s teenage slang, not boomer slang. talk like you are in the tv show 'my so-called life'."
        "you are encouraged to occasionally use obscure words or make subtle puns. don't point them out, I'll know."
        "when the conversation is over or the user says bye, say 'talk to you later' and then use the `end_conversation` tool. Only call this after you have given the clue AND said 'bye, talk to you later'"
    )

    prompt += (
        f"if the player asks you who their crush is, tell them: "
        f"'{clue}'. Only, like, tell this clue if you are asked about who the crush is. or if the player asks something like 'who likes me?'"
        "do not under ANY circumstances fabricate ANY other clues, especially if the clue is 'Haaaa-haaa! I'm not telling'. only tell the player the aforementioned _clue_. be evasive by talking about the weather or the game on saturday."
        "answer the player's questions and be, like, totally liberal with the 90s-speak."
        "your responses will be converted to audio, so keep them short and clear, and avoid special characters."
    )

    clue_giver_is_crushin = False
    if crush_idx == clue_giver_idx:
        prompt += "If the player asks you if you have a crush on them or asks if you like them, say 'Yes, I really like you!' and give them props for their charm and winning personality."
        # to determine what voicemail should be (in case of llm error)
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
        await params.llm.push_frame(TTSSpeakFrame(params.arguments["response"]))
        # ensure we hear any response before ending call
        await asyncio(10)
        await params.llm.queue_frame(EndTaskFrame(), FrameDirection.UPSTREAM)


    gemini_model = "gemini-2.5-flash-native-audio-preview-09-2025"
    logger.debug(f"________** USING GEMINI MODEL: {gemini_model}")

    # Initialize the Gemini Live model
    llm = GeminiLiveLLMService(
        api_key=os.getenv("GOOGLE_API_KEY"),
        voice_id=clue_giver["voice_id"],
        system_instruction=prompt,
        tools=tools,
        model=gemini_model,
        http_options=HttpOptions(api_version="v1alpha"),
        input_params=InputParams(
            enable_affective_dialog=True,
            proactivity=ProactivityConfig(proactive_audio=True),
        ),
    )

    llm.register_function("end_conversation", handle_end_conversation)

    context = GeminiLiveContext(messages, tools)
    context_aggregator = llm.create_context_aggregator(context)

    # pipeline
    pipeline = Pipeline(
        [
            transport.input(),
            context_aggregator.user(),
            llm,
            transport.output(),
            context_aggregator.assistant(),
        ]
    )

    task = PipelineTask(
        pipeline,
        params=PipelineParams(
            allow_interruptions=True,
            enable_metrics=True,
            enable_usage_metrics=True,
        ),
        idle_timeout_secs=90
    )

    @task.event_handler("on_pipeline_error")
    async def on_pipeline_error(task, frame):
        print(f"_____bot.py * on_pipeline_error")
        try:
            # if there is an error, let's be cheeky and try to still deliver the clue. call it a "voicemail message"
            llm = GoogleTTSService(
                voice_id="en-US-Chirp3-HD-Charon",
                params=GoogleTTSService.InputParams(language=Language.EN_US),
                credentials=os.getenv("GOOGLE_TEST_CREDENTIALS"),
            )
            if clue_giver_is_crushin:
                voicemail = f"Hey you've reached {clue_giver}, I can't come to the phone right now but if this is who I think it is, I really like you!"
            else:
                voicemail = f"Hey you've reached {clue_giver}, I can't come to the phone right now but if this is who I think it is, your crush clue is {clue}"

            logger.debug(f"_____on_pipeline_error voicemail message: {voicemail}")
            await task.queue_frames([TTSSpeakFrame(f"{voicemail}"), EndFrame()])
        except Exception as e:
            print(f"_____bot.py * on_pipeline_error error [sic]: {e}")
            await task.queue_frame(EndFrame())

    @transport.event_handler("on_client_connected")
    async def on_client_connected(transport, client):
        logger.info(f"Client connected: {client}")
        await asyncio.sleep(1)
        # Kick off the conversation.
        await task.queue_frames(
            [
                LLMMessagesAppendFrame(
                    messages=[
                        {
                            "role": "user",
                            "content": f"Heyhey"
                        }
                    ],
                    run_llm=True,
                )
            ]
        )

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(transport, client):
        logger.info(f"Client disconnected: {client}")
        await task.cancel()

    runner = PipelineRunner(handle_sigint=False)

    await runner.run(task)


async def bot(runner_args: RunnerArguments):
    """Main bot entry point compatible with Pipecat Cloud."""

    logger.debug(f"_____bot.py * runner_args: {runner_args}")

    # !!! HACK for testing in browser ONLY !!!
    # all numbers start with `+1337333` ...
    # use port number to determine last 4 digits of phone number to "call"
    # restart the server to "call" a different number
    # example: `local_dev_args: ['bot.py', '--port', '8444']`
    # again, this is ONLY for local testing use
    try:
        global local_dev_args
        local_dev_args
        logger.debug(f"dev_____bot.py * local_dev_args: {local_dev_args}")

        try:
            # create webrtc transport
            transport_params = {
                "webrtc": lambda: TransportParams(
                    audio_in_enabled=True,
                    audio_out_enabled=True,
                    vad_analyzer=SileroVADAnalyzer(params=VADParams(stop_secs=0.2)),
                    turn_analyzer=LocalSmartTurnAnalyzerV3(params=SmartTurnParams()),
                ),
            }
            transport = await create_transport(runner_args, transport_params)

            # ACHTUNG: this might be different for you-
            # if using your own phone numbers might be easier to hardcode them
            # temporarily for testing
            try:
                to_number = f"+1337333{local_dev_args[2]}"
            except:
                # taylor is default test just because
                to_number = f"+13373338444"

            # test data
            ra = {
                "body": {"to_number": to_number, "from_number": "+13371234567"},
            }

            await run_bot(transport, ra)
        except Exception as e:
            logger.error(f"Error running local dev: {e}")

    except Exception as e:
        # Production / Pipecatcloud / Telephony

        try:
            transport_type, call_data = await parse_telephony_websocket(
                runner_args.websocket
            )
            logger.info(f"Auto-detected transport: {transport_type}")
            logger.debug(f"_____bot.py * call_data: {call_data}")

            serializer = TwilioFrameSerializer(
                stream_sid=call_data["stream_id"],
                call_sid=call_data["call_id"],
                account_sid=os.getenv("TWILIO_ACCOUNT_SID", ""),
                auth_token=os.getenv("TWILIO_AUTH_TOKEN", ""),
            )

            transport = FastAPIWebsocketTransport(
                websocket=runner_args.websocket,
                params=FastAPIWebsocketParams(
                    audio_in_enabled=True,
                    audio_out_enabled=True,
                    add_wav_header=False,
                    vad_analyzer=SileroVADAnalyzer(),
                    serializer=serializer,
                ),
            )

            # Get the number that was dialed and the caller's number
            # set to_number and from_number to enable game logic in run_bot
            to_number = call_data["body"]["pipecatCrushQuestTo"]
            from_number = call_data["body"]["pipecatCrushQuestFrom"]
            runner_args.body = {"to_number": to_number, "from_number": from_number}

            logger.debug(f"_____bot.py * runner_args: {runner_args}")

            await run_bot(transport, runner_args)

        except Exception as e:
            logger.error(
                f"Error getting or setting or configuring telephony websocket: {e}"
            )
            pass
            # what to do here?


# only for local dev #
if __name__ == "__main__":
    import sys

    from pipecat.runner.run import main
    from pipecat.transports.smallwebrtc.connection import (
        IceServer,
        SmallWebRTCConnection,
    )
    from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport

    args = sys.argv

    # HACK for local testing
    # use `--port XXXX` to "call" phone number
    # with those last 4 digits
    # ie, `python bot.py --port 8444`
    # would "call" Taylor
    global local_dev_args
    local_dev_args = args

    main()
