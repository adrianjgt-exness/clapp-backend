from .model import QuestionReportCreate, QuestionReportInDB
from config import db, logger

reports_collection = db.question_reports


class QuestionReportService:
    @staticmethod
    async def create_report(report_data: QuestionReportCreate) -> str:
        """
        Saves a new question report to the database.
        """
        try:
            new_report = QuestionReportInDB(**report_data.model_dump())
            result = await reports_collection.insert_one(
                new_report.model_dump(by_alias=True)
            )
            logger.info(
                f"New report created for question {report_data.question_id} by user {report_data.user_id}"
            )
            return str(result.inserted_id)
        except Exception as e:
            logger.error(f"Failed to create question report: {e}")
            raise
