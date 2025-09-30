import os

# --- Development Mode: Load secrets from Vault ---
# This block will only run if APP_ENV is 'dev'. It will safely fail
# in UAT/prod where vault_config.py doesn't exist.
if os.getenv("APP_ENV") == "dev":
    try:
        from vault_config import load_secrets_from_vault

        load_secrets_from_vault()
    except ImportError:
        # This is expected in UAT/prod, so we can ignore it.
        pass
    except Exception as e:
        # Halt the application if dev secrets fail to load.
        print(f"FATAL: Could not load development secrets from Vault: {e}")
        exit(1)

from bson.json_util import dumps
from config import logger, mongo_client, settings
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import json
from modules.auth import controller as auth_controller
from modules.cloudflare import cloudflare_router
from modules.disputes import controller as dispute_controller
from modules.frontend_logs import controller as frontend_log_controller
from modules.hibob import controller as hibob_controller
from modules.jira import controller as jira_controller
from modules.question_reports import controller as question_report_controller
from modules.questions import controller as question_controller
from modules.study_sessions import controller as study_session_controller
from modules.test_sessions import controller as test_session_controller
from modules.test_templates import controller as test_template_controller
from modules.tests import controller as test_controller
from modules.user_reports import controller as user_report_controller
from modules.user_sessions import controller as user_session_controller
from modules.users import controller as user_controller
import sentry_sdk
from starlette.middleware.sessions import SessionMiddleware

from services.ist_dashboard import controller as ist_dashboard_controller

# --- Integrate Sentry with the App ---
SENTRY_DSN = os.getenv("SENTRY_DSN")
if SENTRY_DSN:
    sentry_sdk.init(dsn=SENTRY_DSN, send_default_pii=True, traces_sample_rate=1.0)
    logger.info("Sentry has been set")

# --- Create the FastAPI App ---
app = FastAPI(
    title="CLAPP Backend API",
    description="The backend service for the CLAPP application.",
    version="1.0.0",
    root_path="/api",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

app.add_middleware(SessionMiddleware, secret_key=settings.SESSION_SECRET_KEY)

# --- Add CORS Middleware ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://clapp.test.env",
        "http://localhost:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Register the Module Routers ---
app.include_router(auth_controller.router)
app.include_router(question_controller.router)
app.include_router(question_report_controller.router)
app.include_router(test_session_controller.router)
app.include_router(frontend_log_controller.router)
app.include_router(user_controller.router)
app.include_router(study_session_controller.router)
app.include_router(test_controller.router)
app.include_router(test_template_controller.router)
app.include_router(user_report_controller.router)
app.include_router(dispute_controller.router)
app.include_router(user_session_controller.router)
app.include_router(hibob_controller.router)
app.include_router(jira_controller.router)
app.include_router(cloudflare_router)

# --- Register the External Services Routers ---
app.include_router(ist_dashboard_controller.router)


# --- Health Check and Utility Endpoints ---
@app.get("/")
def home():
    logger.info("Home page accessed")
    return {"message": "Welcome to CLApp!"}


@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.get("/ping-mongo")
async def ping_mongo():
    logger.info("\n--- PING MONGO DIAGNOSTIC STARTED ---")
    try:
        # 1. Get the raw BSON dictionary from MongoDB
        result_from_mongo = await mongo_client.admin.command("ping")

        # 2. Use bson.json_util.dumps to create a JSON string.
        #    This correctly handles the BSON types.
        json_string = dumps(result_from_mongo)

        # 3. Use the standard json.loads to parse the string.
        #    This will create a simple, clean dictionary without any special types.
        final_result = json.loads(json_string)

        # 4. Return the clean dictionary. This will not fail.
        return JSONResponse(
            status_code=200, content={"status": "ok", "result": final_result}
        )

    except Exception as e:
        # Log the full exception traceback to the console
        logger.error(f"MongoDB ping failed: {e}", exc_info=True)
        # Return a clear error message
        return JSONResponse(
            content={"status": "error", "detail": "An internal error occurred."},
            status_code=500,
        )
