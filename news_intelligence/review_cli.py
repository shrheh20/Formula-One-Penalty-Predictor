"""Local CLI for reviewing and publishing news intelligence items."""

from __future__ import annotations

import argparse
import json
from typing import Iterable

from sqlalchemy.exc import OperationalError

from .db import SessionLocal
from .models import NewsArticle, NewsCluster, NewsReviewTask, NewsSummary
from .service import NewsIngestionService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Review and publish Formula 1 news intelligence items from the local workstation.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    queue_parser = subparsers.add_parser("queue", help="Show the current review queue.")
    queue_parser.add_argument("--limit", type=int, default=20, help="Maximum number of review tasks to show.")
    queue_parser.add_argument(
        "--status",
        choices=["open", "closed", "all"],
        default="open",
        help="Filter review tasks by status.",
    )

    show_parser = subparsers.add_parser("show", help="Show a cluster, article, or task in detail.")
    show_parser.add_argument("target_type", choices=["cluster", "article", "task"])
    show_parser.add_argument("target_id", type=int)

    approve_parser = subparsers.add_parser("approve", help="Approve a cluster, article, or task.")
    approve_parser.add_argument("target_type", choices=["cluster", "article", "task"])
    approve_parser.add_argument("target_id", type=int)
    approve_parser.add_argument("--notes", default="", help="Optional approval notes.")

    reject_parser = subparsers.add_parser("reject", help="Reject a cluster, article, or task.")
    reject_parser.add_argument("target_type", choices=["cluster", "article", "task"])
    reject_parser.add_argument("target_id", type=int)
    reject_parser.add_argument("--notes", default="", help="Optional rejection notes.")

    stats_parser = subparsers.add_parser("stats", help="Show live store counts.")
    stats_parser.add_argument("--json", action="store_true", help="Emit counts as JSON.")

    return parser


def print_queue(limit: int, status: str) -> int:
    session = SessionLocal()
    try:
        query = session.query(NewsReviewTask).order_by(NewsReviewTask.created_at.desc(), NewsReviewTask.id.desc())
        if status != "all":
            query = query.filter(NewsReviewTask.status == status)
        tasks = query.limit(limit).all()
        if not tasks:
            print("No review tasks found.")
            return 0

        for task in tasks:
            label = resolve_target_label(session, task.target_type, task.target_id)
            print(
                f"[{task.id}] {task.status.upper()} {task.priority.upper()} "
                f"{task.target_type}:{task.target_id} {task.reason_type}"
            )
            print(f"  {label}")
            print(f"  {task.reason_summary}")
            if task.resolution:
                print(f"  resolution={task.resolution}")
        return 0
    finally:
        session.close()


def print_show(target_type: str, target_id: int) -> int:
    session = SessionLocal()
    try:
        if target_type == "task":
            task = session.query(NewsReviewTask).filter(NewsReviewTask.id == target_id).one_or_none()
            if task is None:
                print("Review task not found.")
                return 1
            payload = {
                "id": task.id,
                "target_type": task.target_type,
                "target_id": task.target_id,
                "reason_type": task.reason_type,
                "reason_summary": task.reason_summary,
                "priority": task.priority,
                "status": task.status,
                "resolution": task.resolution,
                "resolution_notes": task.resolution_notes,
                "agent_payload": task.agent_payload,
            }
            print(json.dumps(payload, indent=2, default=str))
            return 0

        if target_type == "cluster":
            cluster = session.query(NewsCluster).filter(NewsCluster.id == target_id).one_or_none()
            if cluster is None:
                print("Cluster not found.")
                return 1
            articles = (
                session.query(NewsArticle)
                .filter(NewsArticle.cluster_id == cluster.id)
                .order_by(NewsArticle.published_at.desc().nullslast(), NewsArticle.id.desc())
                .all()
            )
            summaries = (
                session.query(NewsSummary)
                .filter(NewsSummary.target_type == "cluster", NewsSummary.target_id == cluster.id)
                .all()
            )
            payload = {
                "id": cluster.id,
                "title": cluster.cluster_title,
                "cluster_type": cluster.cluster_type,
                "grand_prix": cluster.grand_prix,
                "review_status": cluster.review_status,
                "publication_status": cluster.publication_status,
                "member_articles": [
                    {
                        "id": article.id,
                        "headline": article.headline,
                        "source": (article.metadata_json or {}).get("source_key"),
                        "review_status": article.review_status,
                        "publication_status": article.publication_status,
                        "canonical_url": article.canonical_url,
                    }
                    for article in articles
                ],
                "summaries": [
                    {
                        "summary_kind": summary.summary_kind,
                        "status": summary.status,
                        "factual_summary": summary.factual_summary,
                        "strategy_impact_summary": summary.strategy_impact_summary,
                        "derived_insight": summary.derived_insight,
                    }
                    for summary in summaries
                ],
            }
            print(json.dumps(payload, indent=2, default=str))
            return 0

        article = session.query(NewsArticle).filter(NewsArticle.id == target_id).one_or_none()
        if article is None:
            print("Article not found.")
            return 1
        summaries = (
            session.query(NewsSummary)
            .filter(NewsSummary.target_type == "article", NewsSummary.target_id == article.id)
            .all()
        )
        payload = {
            "id": article.id,
            "headline": article.headline,
            "canonical_url": article.canonical_url,
            "source": (article.metadata_json or {}).get("source_key"),
            "grand_prix": article.grand_prix,
            "review_status": article.review_status,
            "publication_status": article.publication_status,
            "claim_status": article.claim_status,
            "chunk_status": article.chunk_status,
            "content_type": (article.metadata_json or {}).get("content_type"),
            "summary_eligible": (article.metadata_json or {}).get("summary_eligible"),
            "clean_text_preview": (article.clean_text or "")[:1000],
            "summaries": [
                {
                    "summary_kind": summary.summary_kind,
                    "status": summary.status,
                    "factual_summary": summary.factual_summary,
                    "strategy_impact_summary": summary.strategy_impact_summary,
                    "derived_insight": summary.derived_insight,
                }
                for summary in summaries
            ],
        }
        print(json.dumps(payload, indent=2, default=str))
        return 0
    finally:
        session.close()


def apply_action(target_type: str, target_id: int, action: str, notes: str) -> int:
    session = SessionLocal()
    service = NewsIngestionService()
    try:
        result = service.apply_review_action(
            session,
            target_type=target_type,
            target_id=target_id,
            action=action,
            notes=notes,
        )
        session.commit()
        print(json.dumps(result, indent=2, default=str))
        return 0
    except ValueError as exc:
        session.rollback()
        print(str(exc))
        return 1
    finally:
        session.close()


def print_stats(as_json: bool) -> int:
    session = SessionLocal()
    try:
        payload = {
            "articles": session.query(NewsArticle).count(),
            "clusters": session.query(NewsCluster).count(),
            "open_review_tasks": session.query(NewsReviewTask).filter(NewsReviewTask.status == "open").count(),
            "approved_articles": session.query(NewsArticle).filter(NewsArticle.publication_status == "approved").count(),
            "approved_clusters": session.query(NewsCluster).filter(NewsCluster.publication_status == "approved").count(),
        }
        if as_json:
            print(json.dumps(payload, indent=2, default=str))
        else:
            for key, value in payload.items():
                print(f"{key}: {value}")
        return 0
    finally:
        session.close()


def resolve_target_label(session, target_type: str, target_id: int) -> str:
    if target_type == "cluster":
        cluster = session.query(NewsCluster).filter(NewsCluster.id == target_id).one_or_none()
        return cluster.cluster_title if cluster else "Unknown cluster"
    if target_type == "article":
        article = session.query(NewsArticle).filter(NewsArticle.id == target_id).one_or_none()
        return article.headline if article else "Unknown article"
    return "Review task"


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    try:
        if args.command == "queue":
            return print_queue(args.limit, args.status)
        if args.command == "show":
            return print_show(args.target_type, args.target_id)
        if args.command == "approve":
            return apply_action(args.target_type, args.target_id, "approve", args.notes)
        if args.command == "reject":
            return apply_action(args.target_type, args.target_id, "reject", args.notes)
        if args.command == "stats":
            return print_stats(args.json)
        parser.error("Unknown command")
        return 2
    except OperationalError as exc:
        print("Could not connect to the configured Postgres database.")
        print("Check that Postgres is running and that NEWS_DATABASE_URL in Formula-One-Penalty-Predictor/.env is correct.")
        print(f"Details: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
