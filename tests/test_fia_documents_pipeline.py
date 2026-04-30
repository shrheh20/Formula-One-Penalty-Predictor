from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from unittest.mock import Mock

from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from fia_documents.api import create_app  # noqa: E402
from fia_documents.classifier import FiaDocumentClassifier  # noqa: E402
from fia_documents.db import Document, SessionLocal, init_db  # noqa: E402
from fia_documents.document_pipeline import DocumentExtractionPipeline, ExtractionEnvelope  # noqa: E402
from fia_documents.fia_scraper import FiaDocumentScraper  # noqa: E402
from fia_documents.llm_client import normalize_chat_completions_url  # noqa: E402
from fia_documents.pdf_parser import PdfProcessingError, PdfProcessor  # noqa: E402
from fia_documents.summary import DashboardSummaryClient  # noqa: E402
from fia_documents.scheduler import (  # noqa: E402
    DocumentIngestionService,
    IngestionScheduler,
    parse_monitor_weekdays,
)


class FiaDocumentsPipelineTests(unittest.TestCase):
    def test_scraper_parses_season_page_rows(self) -> None:
        html = """
        <div class="decision-document-list">
          <ul class="event-wrapper">
            <li>
              <div class="event-title">Japanese Grand Prix</div>
              <ul>
                <li class="document-row">
                  <div class="title">Doc 12 - Decision - Car 81</div>
                  <div class="published"><span class="date-display-single">06.04.26 18:22</span></div>
                  <a href="/system/files/doc12.pdf">PDF</a>
                </li>
              </ul>
            </li>
          </ul>
        </div>
        """

        scraper = FiaDocumentScraper(extra_page_urls=[])
        documents = scraper.parse_documents(
            html,
            page_url="https://www.fia.com/documents/.../event/Japanese%20Grand%20Prix",
        )

        self.assertEqual(len(documents), 1)
        document = documents[0]
        self.assertEqual(document.doc_number, 12)
        self.assertEqual(document.title, "Decision - Car 81")
        self.assertEqual(document.grand_prix, "Japanese Grand Prix")
        self.assertEqual(document.pdf_url, "https://www.fia.com/system/files/doc12.pdf")
        self.assertEqual(
            document.source_page_url,
            "https://www.fia.com/documents/.../event/Japanese%20Grand%20Prix",
        )

    def test_scraper_parses_event_page_without_event_wrapper(self) -> None:
        html = """
        <html>
          <head><title>Formula 1 Bahrain Grand Prix documents</title></head>
          <body>
            <h1 class="page-title">Bahrain Grand Prix</h1>
            <div class="decision-document-list">
              <ul>
                <li class="document-row">
                  <div class="title">Recalled - Doc 4 - Technical Directive TD001</div>
                  <div class="published"><span class="date-display-single">05.03.26 09:00</span></div>
                  <div class="recalled-document">Recalled</div>
                  <a href="/system/files/td001.pdf">PDF</a>
                </li>
              </ul>
            </div>
          </body>
        </html>
        """

        scraper = FiaDocumentScraper(extra_page_urls=[])
        documents = scraper.parse_documents(html)

        self.assertEqual(len(documents), 1)
        document = documents[0]
        self.assertEqual(document.grand_prix, "Bahrain Grand Prix")
        self.assertTrue(document.is_recalled)
        self.assertEqual(document.title, "Technical Directive TD001")

    def test_document_classifier_maps_requested_taxonomy(self) -> None:
        cases = [
            ("Technical Directive TD018", "technical_directive", "technical_directive"),
            ("Decision - Car 81", "steward_decision", "steward_decision"),
            ("New PU Elements for this Competition", "new_pu_elements", "component_allocation"),
            ("Final Race Classification", "final_race_classification", "sporting_results"),
            ("Competition Notes - Pirelli Preview V2", "competition_notes_pirelli_preview_v2", "race_control"),
            ("Car Display Procedure", "car_display_procedure", "procedure"),
            ("Entry List", "entry_list", "sporting_results"),
            ("Post-Race checks", "post_race_checks", "scrutineering"),
            ("Final Sprint Classification", "final_sprint_classification", "sporting_results"),
            ("Timetable", "timetable", "race_control"),
            (
                "Summons - Car 6 - Alleged Failure to follow Race Director's Instructions",
                "summons",
                "steward_decision",
            ),
        ]

        for title, expected_type, expected_family in cases:
            result = FiaDocumentClassifier.classify_with_rules(title=title, text=title)
            self.assertEqual(result.document_type, expected_type)
            self.assertEqual(result.document_family, expected_family)

    def test_pipeline_exposes_classification_metadata_in_source(self) -> None:
        pipeline = DocumentExtractionPipeline()
        extraction = pipeline.extract(
            title="Final Starting Grid",
            text="Final Starting Grid\n1 81 Oscar Piastri McLaren 1:27.000",
            grand_prix="Japanese Grand Prix",
            doc_number=33,
            is_recalled=False,
        )

        self.assertEqual(extraction.document_type, "final_starting_grid")
        self.assertEqual(extraction.document_family, "sporting_results")
        self.assertIn("classification", extraction.extracted_data["source"])

    def test_merge_normalizes_llm_dict_entities(self) -> None:
        merged = DocumentExtractionPipeline._merge_outputs(
            parser_output={
                "document_type": "entry_list",
                "document_family": "sporting_results",
                "session": None,
                "car_numbers": [],
                "drivers": [],
                "teams": [],
                "articles_cited": [],
                "penalty_type": None,
                "grid_penalty_places": None,
                "lap_time_deleted": False,
                "incident_summary": "Entry List",
                "verdict_summary": None,
                "entries": [],
                "table_rows": [],
                "unknown_document_signals": [],
            },
            ai_result={
                "document_type": "entry_list",
                "document_family": "sporting_results",
                "drivers": [{"driver": "Oscar Piastri"}, {"name": "Lando Norris"}],
                "teams": [{"team": "McLaren Mercedes"}, {"constructor": "Ferrari"}],
                "car_numbers": ["81", "4", "81"],
            },
        )

        self.assertEqual(merged["drivers"], ["Oscar Piastri", "Lando Norris"])
        self.assertEqual(merged["teams"], ["McLaren Mercedes", "Ferrari"])
        self.assertEqual(merged["car_numbers"], [4, 81])

    def test_entry_list_line_maps_constructor_to_canonical_team(self) -> None:
        pipeline = DocumentExtractionPipeline()
        parsed = pipeline._parse_entry_list_line(
            "81 PIA Oscar Piastri AUS McLaren Mercedes"
        )

        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed["driver"], "Oscar Piastri")
        self.assertEqual(parsed["team"], "McLaren Mastercard F1 Team")

    def test_championship_driver_line_prefers_known_driver_and_last_points_value(self) -> None:
        pipeline = DocumentExtractionPipeline()
        parsed = pipeline._parse_championship_driver_line(
            "1 O. PIASTRI 34 59 84",
            pipeline._driver_abbreviation_map(),
        )

        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed["driver"], "Oscar Piastri")
        self.assertEqual(parsed["position"], 1)
        self.assertEqual(parsed["total_points"], 84)

    def test_unknown_document_edge_case_is_explicitly_flagged(self) -> None:
        pipeline = DocumentExtractionPipeline()
        extraction = pipeline.extract(
            title="Garage Access Advisory",
            text="Garage Access Advisory\nAll Teams must report to the media pen before 09:00.",
            grand_prix="Chinese Grand Prix",
            doc_number=99,
            is_recalled=False,
        )

        self.assertEqual(extraction.document_type, "other")
        self.assertEqual(extraction.document_family, "other")
        self.assertIn("unknown_document_requires_taxonomy_review", extraction.extracted_data["validation_issues"])
        self.assertTrue(
            any(signal.startswith("unknown_document_title:garage_access_advisory") for signal in extraction.extracted_data["unknown_document_signals"])
        )
        self.assertIn("unknown_document_requires_taxonomy_review", extraction.extracted_data["validation_issues"])

    def test_pdf_processor_raises_clear_error_when_pdfminer_is_unavailable(self) -> None:
        processor = PdfProcessor(data_dir=str(PROJECT_ROOT / "data" / "test_docs"))

        with patch("fia_documents.pdf_parser.pdfminer_extract_text", None):
            with self.assertRaises(PdfProcessingError) as context:
                processor.extract_text("/tmp/missing.pdf")

        self.assertIn("pdfminer.six is not installed", str(context.exception))

    def test_llm_url_normalization_accepts_base_or_full_endpoint(self) -> None:
        self.assertEqual(
            normalize_chat_completions_url("http://localhost:11434"),
            "http://localhost:11434/v1/chat/completions",
        )
        self.assertEqual(
            normalize_chat_completions_url("http://localhost:11434/v1"),
            "http://localhost:11434/v1/chat/completions",
        )
        self.assertEqual(
            normalize_chat_completions_url("http://localhost:11434/v1/chat/completions"),
            "http://localhost:11434/v1/chat/completions",
        )

    def test_monitor_weekday_parser_and_scheduler_description(self) -> None:
        weekdays = parse_monitor_weekdays("3,4,6")
        self.assertEqual(weekdays, (3, 4, 6))

        scheduler = IngestionScheduler(
            ingestion_service=DocumentIngestionService(),
            interval_seconds=1800,
            run_weekend_only=True,
            timezone_name="America/Chicago",
            active_weekdays=weekdays,
        )
        description = scheduler.describe()
        self.assertTrue(description["enabled"])
        self.assertEqual(description["interval_seconds"], 1800)
        self.assertTrue(description["run_weekend_only"])
        self.assertEqual(description["active_weekdays"], [3, 4, 6])

    def test_dashboard_summary_client_falls_back_without_llm(self) -> None:
        with patch.dict("os.environ", {}, clear=False):
            client = DashboardSummaryClient()
            result = client.summarize(
                title="Final Race Classification",
                grand_prix="Japanese Grand Prix",
                document_type="final_race_classification",
                document_family="sporting_results",
                raw_text="Final Race Classification after 53 laps.",
                extracted_data={"session": "Race", "drivers": ["Oscar Piastri"]},
            )

        self.assertEqual(result["provider"], "fallback")
        self.assertEqual(result["doc_type"], "FINAL_RACE_RESULT")
        self.assertEqual(result["impact_level"], "HIGH")
        self.assertIn("### Race Impact", result["summary"])
        self.assertIn("official competitive order", result["summary"])

    def test_dashboard_summary_client_bypasses_llm_for_admin_documents(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "LLM_API_URL": "http://localhost:11434",
                "LLM_API_KEY": "dummy",
                "LLM_MODEL": "qwen3.5:2b",
            },
            clear=False,
        ):
            client = DashboardSummaryClient()
            with patch("fia_documents.summary.requests.post") as mocked_post:
                result = client.summarize(
                    title="Entry List",
                    grand_prix="Japanese Grand Prix",
                    document_type="entry_list",
                    document_family="sporting_results",
                    raw_text="81 Oscar Piastri McLaren Mercedes",
                    extracted_data={"drivers": ["Oscar Piastri"], "teams": ["McLaren Mercedes"]},
                )

        mocked_post.assert_not_called()
        self.assertEqual(result["provider"], "rule_based")
        self.assertEqual(
            result["summary"],
            "### Race Impact\n\n- No meaningful performance or sporting impact.",
        )
        self.assertEqual(result["doc_type"], "ENTRY_LIST")
        self.assertEqual(result["impact_level"], "LOW")

    def test_dashboard_summary_client_formats_llm_race_impact_output(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "SUMMARY_LLM_API_URL": "https://api.mistral.ai",
                "SUMMARY_LLM_API_KEY": "mistral-test-key",
                "SUMMARY_LLM_MODEL": "mistral-small-2603",
            },
            clear=False,
        ):
            client = DashboardSummaryClient()
            fake_response = Mock()
            fake_response.json.return_value = {
                "choices": [
                    {
                        "message": {
                            "content": (
                                "### Race Impact\n"
                                "- Lando Norris had a qualifying lap deleted for track limits.\n"
                                "- McLaren faces a change to the starting order."
                            )
                        }
                    }
                ]
            }
            fake_response.raise_for_status.return_value = None

            with patch("fia_documents.summary.requests.post", return_value=fake_response):
                result = client.summarize(
                    title="Infringement - Qualifying Deleted Lap Times",
                    grand_prix="Japanese Grand Prix",
                    document_type="infringement_qualifying_deleted_lap_times",
                    document_family="steward_decision",
                    raw_text="Deleted lap times were applied for track limits.",
                    extracted_data={
                        "session": "Qualifying",
                        "drivers": ["Lando Norris"],
                        "teams": ["McLaren Mercedes"],
                        "penalty_type": "deleted_lap_times",
                    },
                )

        self.assertEqual(result["provider"], "llm")
        self.assertEqual(result["doc_type"], "QUALI_TRACK_LIMITS")
        self.assertEqual(result["impact_level"], "HIGH")
        self.assertIn("### Race Impact", result["summary"])
        self.assertIn("**Lando Norris (McLaren)**", result["summary"])

    def test_dashboard_summary_client_prefers_summary_specific_env_vars(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "LLM_API_URL": "http://localhost:11434",
                "LLM_API_KEY": "dummy",
                "LLM_MODEL": "qwen3.5:2b",
                "SUMMARY_LLM_API_URL": "https://api.mistral.ai",
                "SUMMARY_LLM_API_KEY": "mistral-test-key",
                "SUMMARY_LLM_MODEL": "mistral-small-2603",
            },
            clear=False,
        ):
            client = DashboardSummaryClient()

        self.assertEqual(client.api_url, "https://api.mistral.ai/v1/chat/completions")
        self.assertEqual(client.api_key, "mistral-test-key")
        self.assertEqual(client.model, "mistral-small-2603")

    def test_reprocess_documents_from_raw_runs_in_batches(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "fia_reprocess.db"
            with patch.dict("os.environ", {"DATABASE_URL": f"sqlite:///{db_path}"}):
                from importlib import reload
                import fia_documents.db as db_module
                import fia_documents.scheduler as scheduler_module

                db_module = reload(db_module)
                scheduler_module = reload(scheduler_module)
                db_module.init_db()

                with db_module.session_scope() as session:
                    session.add(
                        db_module.Document(
                            doc_number=12,
                            title="Decision - Car 81",
                            grand_prix="Japanese Grand Prix",
                            pdf_url="https://example.com/doc12.pdf",
                            processed=False,
                            raw_text="Decision document text for Car 81.",
                            extraction_status="processing_failed",
                            needs_review=True,
                        )
                    )
                    session.add(
                        db_module.Document(
                            doc_number=13,
                            title="Final Race Classification",
                            grand_prix="Japanese Grand Prix",
                            pdf_url="https://example.com/doc13.pdf",
                            processed=False,
                            raw_text="Final race classification after 53 laps.",
                            extraction_status="processing_failed",
                            needs_review=True,
                        )
                    )

                fake_extraction = ExtractionEnvelope(
                    document_type="steward_decision",
                    document_family="steward_decision",
                    extraction_status="ready",
                    extraction_version="test-version",
                    extraction_confidence=0.91,
                    needs_review=False,
                    parser_output={"parser_strategy": "test", "confidence": 0.91, "unknown_document_signals": []},
                    extracted_data={"drivers": ["Lando Norris"], "teams": ["McLaren Mercedes"]},
                    ai_result={"provider": "failed", "confidence": 0.0, "reason": "timeout"},
                )
                extraction_pipeline = Mock()
                extraction_pipeline.extract.return_value = fake_extraction

                summary_client = Mock()
                summary_client.summarize.return_value = {
                    "doc_type": "STEWARDS_DECISION",
                    "impact_level": "HIGH",
                    "drivers_affected": ["Lando Norris"],
                    "teams_affected": ["McLaren"],
                    "race_impact_summary": "### Race Impact\n\n- Test summary.",
                    "summary": "### Race Impact\n\n- Test summary.",
                    "provider": "llm",
                    "version": "summary-test",
                }

                service = scheduler_module.DocumentIngestionService(
                    extraction_pipeline=extraction_pipeline,
                    summary_client=summary_client,
                )

                result = service.reprocess_documents_from_raw(
                    grand_prix="Japanese Grand Prix",
                    batch_size=1,
                    max_documents=2,
                    clear_failed_ai_result=True,
                )

                self.assertEqual(result["batches"], 2)
                self.assertEqual(result["processed"], 2)
                self.assertEqual(result["failed"], 0)

                with db_module.session_scope() as session:
                    docs = session.query(db_module.Document).order_by(db_module.Document.id.asc()).all()
                    self.assertEqual(len(docs), 2)
                    self.assertTrue(all(doc.processed for doc in docs))
                    self.assertTrue(all(doc.dashboard_summary == "### Race Impact\n\n- Test summary." for doc in docs))
                    self.assertTrue(all(doc.ai_result is None for doc in docs))

    def test_insights_endpoint_returns_dashboard_cards(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "fia_test.db"
            with patch.dict("os.environ", {"DATABASE_URL": f"sqlite:///{db_path}"}):
                from importlib import reload
                import fia_documents.db as db_module
                import fia_documents.api as api_module

                db_module = reload(db_module)
                api_module = reload(api_module)
                db_module.init_db()

                with db_module.session_scope() as session:
                    session.add(
                        db_module.Document(
                            doc_number=28,
                            title="Decision - Car 12 - Alleged impeding of Car 1",
                            grand_prix="Chinese Grand Prix",
                            processed=True,
                            document_type="steward_decision",
                            document_family="steward_decision",
                            extraction_status="ready",
                            extraction_confidence=0.95,
                            needs_review=False,
                            dashboard_summary=(
                                "Stewards reviewed the alleged impeding incident involving Car 12 in qualifying. "
                                "The ruling recorded no further action for Kimi Antonelli, so the weekend order was left unchanged."
                            ),
                            dashboard_summary_provider="llm",
                            extracted_data={
                                "drivers": ["Kimi Antonelli"],
                                "teams": ["Mercedes-AMG PETRONAS F1 Team"],
                                "session": "Qualifying",
                                "penalty_type": "no_further_action",
                                "source": {
                                    "llm_used": True,
                                    "classification": {"provider": "rules"},
                                },
                            },
                        )
                    )

                app = api_module.create_app(
                    ingestion_service=DocumentIngestionService(),
                    scheduler=None,
                )
                client = TestClient(app)

                response = client.get("/insights/latest?limit=3")
                self.assertEqual(response.status_code, 200)
                payload = response.json()
                self.assertEqual(payload["summary"]["highlights_returned"], 1)
                self.assertIn("steward action", payload["headline"])
                self.assertEqual(payload["highlights"][0]["category_label"], "Stewards")
                self.assertEqual(payload["highlights"][0]["what_happened"], "Stewards published an official decision with a no further action outcome.")
                self.assertIn("dashboard_summary", payload["highlights"][0])
                self.assertIn("weekend order was left unchanged", payload["highlights"][0]["dashboard_summary"])
                self.assertIn("critical_highlights", payload)

    def test_insights_prioritize_stewards_over_newer_results(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "fia_priority.db"
            with patch.dict("os.environ", {"DATABASE_URL": f"sqlite:///{db_path}"}):
                from importlib import reload
                import fia_documents.db as db_module
                import fia_documents.api as api_module

                db_module = reload(db_module)
                api_module = reload(api_module)
                db_module.init_db()

                with db_module.session_scope() as session:
                    session.add(
                        db_module.Document(
                            doc_number=90,
                            title="Final Race Classification",
                            grand_prix="Japanese Grand Prix",
                            processed=True,
                            document_type="final_race_classification",
                            document_family="sporting_results",
                            extraction_status="ready",
                            extracted_data={"session": "Race"},
                        )
                    )
                    session.add(
                        db_module.Document(
                            doc_number=91,
                            title="Decision - Car 81",
                            grand_prix="Japanese Grand Prix",
                            processed=True,
                            document_type="steward_decision",
                            document_family="steward_decision",
                            extraction_status="ready",
                            extracted_data={"drivers": ["Oscar Piastri"], "penalty_type": "warning"},
                        )
                    )

                app = api_module.create_app(
                    ingestion_service=DocumentIngestionService(),
                    scheduler=None,
                )
                client = TestClient(app)

                response = client.get("/insights/latest?limit=2")
                self.assertEqual(response.status_code, 200)
                payload = response.json()
                self.assertEqual(payload["highlights"][0]["document_family"], "steward_decision")

    def test_insights_use_distinct_copy_for_results_documents(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "fia_results_copy.db"
            with patch.dict("os.environ", {"DATABASE_URL": f"sqlite:///{db_path}"}):
                from importlib import reload
                import fia_documents.db as db_module
                import fia_documents.api as api_module

                db_module = reload(db_module)
                api_module = reload(api_module)
                db_module.init_db()

                with db_module.session_scope() as session:
                    session.add(
                        db_module.Document(
                            doc_number=77,
                            title="Championship Points",
                            grand_prix="Japanese Grand Prix",
                            processed=True,
                            document_type="championship_points",
                            document_family="sporting_results",
                            extraction_status="ready",
                            extracted_data={"session": "Race"},
                        )
                    )
                    session.add(
                        db_module.Document(
                            doc_number=78,
                            title="Final Race Classification",
                            grand_prix="Japanese Grand Prix",
                            processed=True,
                            document_type="final_race_classification",
                            document_family="sporting_results",
                            extraction_status="ready",
                            extracted_data={"session": "Race"},
                        )
                    )

                app = api_module.create_app(
                    ingestion_service=DocumentIngestionService(),
                    scheduler=None,
                )
                client = TestClient(app)

                response = client.get("/insights/latest?limit=4")
                self.assertEqual(response.status_code, 200)
                payload = response.json()
                happened_lines = {item["title"]: item["what_happened"] for item in payload["highlights"]}
                self.assertIn("Official championship standings were updated", happened_lines["Championship Points"])
                self.assertIn("Final Race Classification confirmed the official order", happened_lines["Final Race Classification"])

    def test_review_queue_and_reprocess_endpoints(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "fia_test.db"
            with patch.dict("os.environ", {"DATABASE_URL": f"sqlite:///{db_path}"}):
                from importlib import reload
                import fia_documents.db as db_module
                import fia_documents.scheduler as scheduler_module
                import fia_documents.api as api_module

                db_module = reload(db_module)
                scheduler_module = reload(scheduler_module)
                api_module = reload(api_module)
                db_module.init_db()

                with db_module.session_scope() as session:
                    session.add(
                        db_module.Document(
                            doc_number=8,
                            title="Car Display Procedure",
                            grand_prix="Chinese Grand Prix",
                            extraction_status="processing_failed",
                            document_type="other",
                            document_family="other",
                            needs_review=True,
                            processed=False,
                        )
                    )

                app = api_module.create_app(
                    ingestion_service=scheduler_module.DocumentIngestionService(),
                    scheduler=None,
                )
                client = TestClient(app)

                response = client.get("/documents/review-queue?failed_only=true")
                self.assertEqual(response.status_code, 200)
                payload = response.json()
                self.assertEqual(payload["count"], 1)

                guard_response = client.post("/documents/reprocess", json={"run_ingestion": False})
                self.assertEqual(guard_response.status_code, 400)

                with patch.object(
                    scheduler_module.DocumentIngestionService,
                    "run_ingestion_cycle",
                    return_value={"processed": 1},
                ):
                    reprocess_response = client.post(
                        "/documents/reprocess",
                        json={
                            "extraction_statuses": ["processing_failed"],
                            "run_ingestion": False,
                        },
                    )

                self.assertEqual(reprocess_response.status_code, 200)
                reprocess_payload = reprocess_response.json()
                self.assertEqual(reprocess_payload["queued"]["queued"], 1)


if __name__ == "__main__":
    unittest.main()
