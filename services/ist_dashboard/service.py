from datetime import datetime
import re
from urllib.parse import parse_qs, quote, urlparse

from fastapi import HTTPException, status

from .model import DuplicateResult, Epic, Issue
from config import logger
from modules.jira.cache_service import cached_search_all_issues as search_all_issues
from modules.jira.service import jira_service

CURRENT_YEAR = datetime.now().year


class ISTDashboardService:
    @staticmethod
    async def fetch_all_tasks_done() -> list[Issue]:
        try:
            jql = f"issuetype = Task AND project = SUPP AND status = Done AND created >= {CURRENT_YEAR}-01-01"
            raw = await search_all_issues(jql)
            return [
                Issue(
                    id=item["id"],
                    key=item["key"],
                    summary=item["fields"]["summary"],
                    status=item["fields"]["status"]["name"],
                    resolved=item["fields"]["created"],
                    epic_link=item["fields"].get("customfield_10006"),
                    assignee=(
                        item["fields"]["assignee"]["displayName"]
                        if item["fields"].get("assignee")
                        else "Error getting name"
                    ),
                    description=item["fields"].get("description"),
                )
                for item in raw
            ]
        except Exception as e:
            logger.error(f"Error fetching completed tasks for current year: {e}")
            raise

    @staticmethod
    async def fetch_inprogress_epics() -> list[Epic]:
        try:
            jql = 'issuetype = Epic AND project = SUPP AND status = "In Progress"'
            raw = await search_all_issues(jql)
            return [
                Epic(
                    id=item["id"],
                    key=item["key"],
                    summary=item["fields"]["summary"],
                    status=item["fields"]["status"]["name"],
                )
                for item in raw
            ]
        except Exception as e:
            logger.error(f"Error fetching EPICs in progress: {e}")
            raise

    @staticmethod
    async def compute_actions_summary() -> dict[str, dict[str, int]]:
        try:
            tasks = await ISTDashboardService.fetch_all_tasks_done()
            epics = await ISTDashboardService.fetch_inprogress_epics()

            epic_map = {e.key: e.summary for e in epics}

            summary: dict[str, dict[str, int]] = {}

            for t in tasks:
                epic_key = t.epic_link
                if not epic_key:
                    continue

                epic_summary = epic_map.get(epic_key)
                if not epic_summary or "Internal Support" not in epic_summary:
                    continue

                region = epic_summary.rsplit(" Internal Support", 1)[0]

                dt = t.resolved
                if isinstance(dt, datetime):
                    month = dt.strftime("%B")
                else:
                    month = datetime.fromisoformat(dt).strftime("%B")

                bucket = f"{region}_actions_in_{month}"
                if bucket not in summary:
                    summary[bucket] = {}

                agent = t.assignee or "Error getting Name"
                summary[bucket][agent] = summary[bucket].get(agent, 0) + 1
                summary[bucket]["total"] = summary[bucket].get("total", 0) + 1

            return summary
        except Exception:
            logger.error("Error computing actions summary", exc_info=True)
            raise

    @staticmethod
    async def cleanup_duplicates() -> list[DuplicateResult]:
        try:
            tasks = await ISTDashboardService.fetch_all_tasks_done()
            thread_map: dict[str, list[tuple[Issue, str]]] = {}

            for t in tasks:
                desc = t.description or ""
                # find all <…> segments
                links = re.findall(r"<([^>]+)>", desc)
                for link in links:
                    # only Slack message links
                    if not link.startswith("https://exness.slack.com"):
                        continue

                    # parse out thread_ts if present
                    parsed = urlparse(link)
                    params = parse_qs(parsed.query)
                    thread_ids = params.get("thread_ts")
                    if thread_ids:
                        group_id = thread_ids[0]  # e.g. "1750049308.373189"
                    else:
                        # fallback to the message timestamp in path: last 19 chars "pXXXXXXXXXXXXX"
                        group_id = parsed.path.rsplit("/", 1)[-1]

                    thread_map.setdefault(group_id, []).append((t, link))

            results: list[DuplicateResult] = []
            for group_id, entries in thread_map.items():
                if len(entries) < 2:
                    continue

                # unpack issues and links
                issues = [e[0] for e in entries]
                # sort by numeric part of key
                sorted_issues = sorted(issues, key=lambda x: int(x.key.split("-")[-1]))
                original = sorted_issues[0].key

                # choose one canonical link to report (first seen)
                canonical_link = entries[0][1]

                for dup in sorted_issues[1:]:
                    await jira_service.add_comment(
                        dup.key, f"Cancelling task as duplicate of {original}"
                    )
                    # dynamically pick the Cancelled transition
                    transitions = await jira_service.get_transitions(dup.key)
                    cancel = next(
                        (
                            t
                            for t in transitions
                            if t.get("to", {}).get("name", "").lower() == "cancelled"
                        ),
                        None,
                    )
                    if not cancel:
                        logger.error(
                            f"No 'Cancelled' transition for {dup.key}, available: {transitions}"
                        )
                        continue

                    await jira_service.transition_issue(dup.key, cancel["id"])

                    results.append(
                        DuplicateResult(
                            original=original,
                            duplicate=dup.key,
                            message_link=canonical_link,
                        )
                    )
            if not results:
                logger.info("No duplicates found")
            return results
        except Exception:
            logger.error("Error during duplicate cleanup", exc_info=True)
            raise

    @staticmethod
    async def fetch_filtered_tasks(
        region: str,
        month: str | None = None,
        agent: str | None = None,
    ) -> list[Issue]:
        """
        Return all Done‐tasks in SUPP for the given region/month/agent combination,
        delegating all filtering to Jira via JQL + paging.
        """
        # 1) pull epics to get the epic keys for each region
        try:
            epics = await ISTDashboardService.fetch_inprogress_epics()
        except HTTPException:
            raise
        except Exception:
            logger.error("Error fetching EPICs for filtered tasks", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Failed to fetch EPICs from Jira",
            )

        # map: regionName -> epicKey
        epic_map: dict[str, str] = {
            e.summary.rsplit(" Internal Support", 1)[0]: e.key for e in epics
        }

        epic_key = epic_map.get(region)
        if not epic_key:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"No in-progress epic found for region '{region}'",
            )

        # 2) build base JQL
        clauses = [
            "project = SUPP",
            "issuetype = Task",
            "status = Done",
            f"'Epic Link' = {epic_key}",
        ]

        # 3) month → resolutiondate range
        if month:
            try:
                m_idx = datetime.strptime(month, "%B").month
            except ValueError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid month name: '{month}'",
                )
            start = f"{CURRENT_YEAR}-{m_idx:02d}-01"
            end_month = 1 if m_idx == 12 else m_idx + 1
            end_year = CURRENT_YEAR + 1 if m_idx == 12 else CURRENT_YEAR
            end = f"{end_year}-{end_month:02d}-01"
            clauses.append(f"created >= '{start}' AND created < '{end}'")
        else:
            clauses.append(
                f"created >= '{CURRENT_YEAR}-01-01' AND created < '{CURRENT_YEAR + 1}-01-01'"
            )

        if agent:
            # NEW: drop trailing/embedded "[X]" from display names
            # e.g. "Valeria Lopez [X]" -> "Valeria Lopez"
            agent_clean = re.sub(r"\s*\[X\]\s*", "", agent).strip()
            # If an email is provided, prefer it as-is.
            if "@" in agent_clean:
                # Jira usually accepts display name or username; if you want username:
                # username = agent_clean.split("@")[0]
                # clauses.append(f'assignee = {username}')
                clauses.append(f'assignee = "{agent_clean}"')
            else:
                # Quote display names with spaces
                if re.search(r"\s", agent_clean):
                    clauses.append(f'assignee = "{agent_clean}"')
                else:
                    clauses.append(f"assignee = {agent_clean}")

        jql = " AND ".join(clauses)
        logger.info(f"Fetch filtered tasks JQL: {jql}")

        # 5) fetch *all* pages
        try:
            raw = await search_all_issues(jql)
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error paging filtered tasks: {e}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Failed to fetch filtered tasks from Jira",
            )

        # 6) map to our Issue model
        out: list[Issue] = []
        for item in raw:
            fields = item.get("fields", {})
            assignee = fields.get("assignee")
            if assignee and "emailAddress" in assignee:
                email = assignee["emailAddress"]
                user = email.split("@")[0] if email.endswith("@exness.com") else email
            else:
                user = "Unassigned"

            out.append(
                Issue(
                    id=item["id"],
                    key=item["key"],
                    summary=fields.get("summary", ""),
                    status=fields.get("status", {}).get("name", ""),
                    resolved=fields.get("created"),
                    epic_link=fields.get("customfield_10006"),
                    assignee=user,
                    description=fields.get("description"),
                )
            )

        return out

    @staticmethod
    async def build_jira_link(
        region: str,
        month: str | None = None,
        agent: str | None = None,
    ) -> str:
        """
        Return a Jira URL that opens the Issues search with the JQL applied.
        No attempt to pick a specific issue or epic.
        """
        try:
            # 1) find the epic key for this region
            epics = await ISTDashboardService.fetch_inprogress_epics()
            mapping = {
                e.summary.rsplit(" Internal Support", 1)[0]: e.key for e in epics
            }
            epic_key = mapping.get(region)
            if not epic_key:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"No in-progress epic found for region '{region}'",
                )

            # 2) build JQL clauses
            clauses = [
                "project = SUPP",
                "issuetype = Task",
                "status = Done",
                f"'Epic Link' = {epic_key}",
            ]

            if agent:
                # NEW: drop [X] from display name before adding to JQL
                agent_clean = re.sub(r"\s*\[X\]\s*", "", agent).strip()
                if "@" in agent_clean:
                    clauses.append(f'assignee = "{agent_clean}"')
                else:
                    if re.search(r"\s", agent_clean):
                        clauses.append(f'assignee = "{agent_clean}"')
                    else:
                        clauses.append(f"assignee = {agent_clean}")

            if month:
                try:
                    # month → ISO date range
                    # e.g. month="February" → 2025-02-01 to 2025-03-01
                    m_idx = datetime.strptime(month, "%B").month
                except ValueError:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Invalid month name: '{month}'",
                    )
                start = f"{CURRENT_YEAR}-{m_idx:02d}-01"
                end = (
                    f"{CURRENT_YEAR + 1}-01-01"
                    if m_idx == 12
                    else f"{CURRENT_YEAR}-{(m_idx + 1):02d}-01"
                )
                # keep dates unquoted as you’ve been using
                clauses.append(f"created >= {start} AND created < {end}")
            else:
                clauses.append(
                    f"created >= {CURRENT_YEAR}-01-01 AND created < {CURRENT_YEAR + 1}-01-01"
                )

            jql = " AND ".join(clauses)
            logger.info(f"Built Jira link JQL: {jql}")
            encoded = quote(jql, safe="")

            # 3) open the Jira search page (no /browse redirection)
            return f"https://jira.exness.io/issues/?jql={encoded}"

        except HTTPException:
            raise
        except Exception:
            logger.error("Error building Jira link", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Failed to build Jira link",
            )

    @staticmethod
    async def compute_actions_summary_v2() -> dict[str, dict[str, int]]:
        """
        Aggregate per region/month:

        - total                                      -> int
        - <agent display name>                       -> int
        - kind::<kind label>                         -> int
        - kind::<kind label>::agent::<agent name>    -> int
        """
        try:
            tasks = await ISTDashboardService.fetch_all_tasks_done()
            epics = await ISTDashboardService.fetch_inprogress_epics()

            # epic key -> epic summary
            epic_map = {e.key: e.summary for e in epics}

            summary: dict[str, dict[str, int]] = {}

            for t in tasks:
                epic_key = t.epic_link
                if not epic_key:
                    continue

                epic_summary = epic_map.get(epic_key)
                if not epic_summary or "Internal Support" not in epic_summary:
                    continue

                # Region name is the part before " Internal Support"
                region = epic_summary.rsplit(" Internal Support", 1)[0]

                # Month from created/resolved (your Issue.resolved currently holds created)
                dt = t.resolved
                if isinstance(dt, datetime):
                    month = dt.strftime("%B")
                else:
                    month = datetime.fromisoformat(dt).strftime("%B")

                bucket = f"{region}_actions_in_{month}"
                if bucket not in summary:
                    summary[bucket] = {}

                # Agent display name (keep as-is, including possible "[X]")
                agent = t.assignee or "Error getting Name"

                # Kind label: use the task summary as provided by Jira
                kind_label = (t.summary or "Unknown").strip()
                kind_key = f"kind::{kind_label}"
                kind_agent_key = f"{kind_key}::agent::{agent}"

                # --- Increments ---
                # Total per bucket
                summary[bucket]["total"] = summary[bucket].get("total", 0) + 1
                # Total per agent (all kinds)
                summary[bucket][agent] = summary[bucket].get(agent, 0) + 1
                # Total per kind (across all agents)
                summary[bucket][kind_key] = summary[bucket].get(kind_key, 0) + 1
                # Per-agent-per-kind
                summary[bucket][kind_agent_key] = (
                    summary[bucket].get(kind_agent_key, 0) + 1
                )

            return summary
        except Exception:
            logger.error("Error computing actions summary v2", exc_info=True)
            raise

    @staticmethod
    async def build_jira_link_v2(
        region: str,
        month: str | None = None,
        agent: str | None = None,
        kind: str | None = None,
    ) -> str:
        """
        Return a Jira URL that opens the Issues search with the JQL applied.
        Supports optional filters by month, agent, and kind (issue summary).
        """

        def _escape_jql_string(s: str) -> str:
            # minimal escaping for JQL phrase matches
            return s.replace("\\", "\\\\").replace('"', r"\"").strip()

        try:
            # 1) find the epic key for this region
            epics = await ISTDashboardService.fetch_inprogress_epics()
            mapping = {
                e.summary.rsplit(" Internal Support", 1)[0]: e.key for e in epics
            }
            epic_key = mapping.get(region)
            if not epic_key:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"No in-progress epic found for region '{region}'",
                )

            # 2) build JQL clauses
            clauses = [
                "project = SUPP",
                "issuetype = Task",
                "status = Done",
                f"'Epic Link' = {epic_key}",
            ]

            if agent:
                # drop [X] from display name before adding to JQL
                agent_clean = re.sub(r"\s*\[X\]\s*", "", agent).strip()
                if "@" in agent_clean:
                    clauses.append(f'assignee = "{_escape_jql_string(agent_clean)}"')
                else:
                    if re.search(r"\s", agent_clean):
                        clauses.append(
                            f'assignee = "{_escape_jql_string(agent_clean)}"'
                        )
                    else:
                        clauses.append(f"assignee = {agent_clean}")

            if kind:
                # Summary is the "kind" being tracked; match as an exact phrase.
                # Text fields don't support '=', so use a phrase query with ~ and quotes.
                kind_phrase = _escape_jql_string(kind)
                clauses.append(f'summary ~ "{kind_phrase}"')

            if month:
                try:
                    # month → ISO date range
                    m_idx = datetime.strptime(month, "%B").month
                except ValueError:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Invalid month name: '{month}'",
                    )
                start = f"{CURRENT_YEAR}-{m_idx:02d}-01"
                end = (
                    f"{CURRENT_YEAR + 1}-01-01"
                    if m_idx == 12
                    else f"{CURRENT_YEAR}-{(m_idx + 1):02d}-01"
                )
                clauses.append(f"created >= {start} AND created < {end}")
            else:
                # default to current year window
                clauses.append(
                    f"created >= {CURRENT_YEAR}-01-01 AND created < {CURRENT_YEAR + 1}-01-01"
                )

            jql = " AND ".join(clauses)
            logger.info(f"Built Jira link JQL (v2): {jql}")
            encoded = quote(jql, safe="")

            # 3) open the Jira search page (no /browse redirection)
            return f"https://jira.exness.io/issues/?jql={encoded}"

        except HTTPException:
            raise
        except Exception:
            logger.error("Error building Jira link v2", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Failed to build Jira link",
            )
