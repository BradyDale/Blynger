"""Plan outbound Webmentions from exact published item documents."""

import copy
from urllib.parse import urljoin

from .shared import ID, RELATIONS, _absolute_url, _digest, _origin


def _source(document, own_origin):
    if not isinstance(document, dict):
        raise ValueError("Published item is not an object.")
    if not ID.fullmatch(str(document.get("id", ""))):
        raise ValueError("Published item has an invalid id.")
    if type(document.get("version")) is not int or document["version"] < 1:
        raise ValueError("Published item has an invalid version.")
    origin = _origin(document.get("origin") or own_origin)
    if origin != _origin(own_origin):
        raise ValueError("Published item does not belong to this Blyg.")
    page = document.get("page")
    if not isinstance(page, str) or not page.strip():
        raise ValueError("Published item has no page URL.")
    source = _absolute_url(urljoin(origin, page), keep_fragment=False)
    if not source.startswith(origin):
        raise ValueError("Published item page lies outside this Blyg.")
    return {
        "source": source,
        "source_id": document["id"],
        "source_version": document["version"],
    }


def _reference(value, relation, own_origin):
    if not isinstance(value, dict):
        raise ValueError(f"{relation} reference is not an object.")
    if relation == "stub" and "url" in value and "origin" not in value:
        return {
            "relation": relation,
            "target_url": _absolute_url(value["url"]),
            "target_origin": None,
            "target_id": None,
            "target_version": None,
        }
    if not ID.fullmatch(str(value.get("id", ""))):
        raise ValueError(f"{relation} reference has an invalid id.")
    if type(value.get("version")) is not int or value["version"] < 1:
        raise ValueError(f"{relation} reference has an invalid version.")
    origin = _origin(value.get("origin") or own_origin)
    cited = value.get("cited")
    target_url = cited.get("url") if isinstance(cited, dict) else None
    if target_url is not None:
        target_url = _absolute_url(target_url)
        if not target_url.startswith(origin):
            target_url = None
    return {
        "relation": relation,
        "target_url": target_url,
        "target_origin": origin,
        "target_id": value["id"],
        "target_version": value["version"],
    }


def _raw_references(document):
    rows = []
    if "stub_of" in document:
        rows.append(("stub", document.get("stub_of")))
    transclusions = document.get("transclusions", [])
    if not isinstance(transclusions, list):
        transclusions = [None]
    rows.extend(("transclusion", value) for value in transclusions)
    if "forked_from" in document:
        rows.append(("fork", document.get("forked_from")))
    if str(document.get("blyg", "")) == "0.4":
        generated = document.get("generated", [])
        if not isinstance(generated, list):
            rows.append(("source", None))
        else:
            for disclosure in generated:
                sources = disclosure.get("sources", []) if isinstance(disclosure, dict) else [None]
                if not isinstance(sources, list):
                    sources = [None]
                rows.extend(("source", value) for value in sources)
    return rows


def _groups(document, own_origin):
    groups = {}
    issues = []
    for relation, raw in _raw_references(document):
        try:
            ref = _reference(raw, relation, own_origin)
            if ref["target_origin"] == _origin(own_origin):
                continue
            identity = (
                ("url", ref["target_url"])
                if ref["target_origin"] is None
                else ("blyg", ref["target_origin"], ref["target_id"])
            )
            group = groups.setdefault(
                identity,
                {
                    "target_url": ref["target_url"],
                    "target_origin": ref["target_origin"],
                    "target_id": ref["target_id"],
                    "relations": {},
                },
            )
            if group["target_url"] is None and ref["target_url"] is not None:
                group["target_url"] = ref["target_url"]
            group["relations"][relation] = ref["target_version"]
        except (TypeError, ValueError) as error:
            issues.append(str(error))
    return groups, issues


def _signature(group):
    return _digest(
        {
            "target_origin": group["target_origin"],
            "target_id": group["target_id"],
            "target_url": group["target_url"] if group["target_origin"] is None else None,
            "relations": group["relations"],
        }
    )


def plan_mentions(previous, current, own_origin):
    """Plan only new or changed remote references from exact item documents.

    Malformed reference rows are isolated in ``issues``. A malformed row can
    therefore never turn a successful publication into a failed one.
    """
    try:
        source = _source(current, own_origin)
    except (TypeError, ValueError) as error:
        return {"events": [], "issues": [str(error)]}
    prior_groups, prior_issues = _groups(previous, own_origin) if isinstance(previous, dict) else ({}, [])
    current_groups, issues = _groups(current, own_origin)
    events = []
    for identity, group in current_groups.items():
        before = prior_groups.get(identity)
        if before is not None and _signature(before) == _signature(group):
            continue
        event = {
            **source,
            "target_url": group["target_url"],
            "target_origin": group["target_origin"],
            "target_id": group["target_id"],
            "relations": sorted(group["relations"], key=RELATIONS.index),
            "target_versions": copy.deepcopy(group["relations"]),
            "withdrawal": False,
        }
        event["key"] = _digest(event)
        events.append(event)
    if current.get("kind") == "withdrawn":
        for identity, group in prior_groups.items():
            if "stub" not in group["relations"] or identity in current_groups:
                continue
            event = {
                **source,
                "target_url": group["target_url"],
                "target_origin": group["target_origin"],
                "target_id": group["target_id"],
                "relations": ["stub"],
                "target_versions": {"stub": group["relations"]["stub"]},
                "withdrawal": True,
            }
            event["key"] = _digest(event)
            events.append(event)
    events.sort(key=lambda event: event["key"])
    return {"events": events, "issues": prior_issues + issues}
