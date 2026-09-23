"""Graph store and query layer.

Backed by NetworkX rather than Neo4j. For a ~90-node case graph the algorithms
are identical (Louvain communities, Brandes betweenness) and the results are
the same; what is lost is distribution, not method. The whole surface is
confined to this module, so swapping in a Cypher-backed implementation means
rewriting one file.

Access control is enforced *here*, in the query layer, and never in the UI
(FR-GOV-1). Every read takes `allowed_tiers` and nodes outside it are dropped
before traversal, so a Standard-tier caller cannot reach a Restricted node by
any path, and cannot infer its existence from a hole in the results either -
paths that depend on a hidden node simply do not exist for that caller.
"""
from __future__ import annotations

import json
from typing import Any, Iterable

import networkx as nx

from . import config


class GraphStore:
    def __init__(self, data: dict[str, Any]):
        self.raw = data
        self.transactions: list[dict[str, Any]] = data.get("transactions", [])
        self.daily_volume: dict[str, Any] = data.get("daily_volume", {})
        self.mo_profiles: dict[str, Any] = data.get("mo_profiles", {})
        self.merges: list[dict[str, Any]] = data.get("merges", [])
        # Keyed on the tier set, never shared between keys: a Restricted-tier
        # result reaching a Standard caller would be a governance failure rather
        # than a caching bug. Cleared whenever the graph itself changes.
        self._centrality_cache: dict[frozenset, dict[str, Any]] = {}

        g = nx.MultiDiGraph()
        for n in data["nodes"]:
            g.add_node(n["id"], label=n["label"], tier=n.get("tier", "standard"),
                       source_record_id=n.get("source_record_id", ""),
                       **n.get("props", {}))
        for e in data["edges"]:
            g.add_edge(e["src"], e["dst"], key=e["id"], type=e["type"],
                       tier=e.get("tier", "standard"),
                       event_time=e.get("event_time"),
                       ingested_time=e.get("ingested_time"),
                       **e.get("props", {}))
        self.g = g

    # ------------------------------------------------------------------ io
    @classmethod
    def load(cls, path=None) -> "GraphStore":
        path = path or config.GRAPH_PATH
        return cls(json.loads(path.read_text(encoding="utf-8")))

    def save(self, path=None) -> None:
        path = path or config.GRAPH_PATH
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        payload = dict(self.raw)
        payload["merges"] = self.merges
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False),
                        encoding="utf-8")

    # -------------------------------------------------------- tier filtering
    def visible(self, allowed_tiers: Iterable[str]) -> nx.MultiDiGraph:
        """The subgraph this caller is permitted to see. All reads go through here."""
        allowed = set(allowed_tiers)
        keep = [n for n, d in self.g.nodes(data=True)
                if d.get("tier", "standard") in allowed]
        sub = self.g.subgraph(keep).copy()
        # Edges carry their own tier: an Elevated edge between two Standard
        # nodes is still hidden from a Standard caller.
        drop = [(u, v, k) for u, v, k, d in sub.edges(keys=True, data=True)
                if d.get("tier", "standard") not in allowed]
        sub.remove_edges_from(drop)
        return sub

    def hidden_count(self, allowed_tiers: Iterable[str]) -> int:
        allowed = set(allowed_tiers)
        return sum(1 for _, d in self.g.nodes(data=True)
                   if d.get("tier", "standard") not in allowed)

    # --------------------------------------------------------------- lookups
    def node(self, node_id: str, allowed_tiers: Iterable[str]) -> dict[str, Any] | None:
        if node_id not in self.g:
            return None
        d = self.g.nodes[node_id]
        if d.get("tier", "standard") not in set(allowed_tiers):
            return None
        return self._node_payload(node_id, d)

    @staticmethod
    def _node_payload(node_id: str, d: dict[str, Any]) -> dict[str, Any]:
        props = {k: v for k, v in d.items()
                 if k not in ("label", "tier", "source_record_id")}
        style = config.NODE_STYLE.get(
            d["label"], {"color": "#8b949e", "glyph": "?", "icon": "document"})
        return {
            "id": node_id,
            "label": d["label"],
            "tier": d.get("tier", "standard"),
            "source_record_id": d.get("source_record_id", ""),
            "props": props,
            "display": _display_name(d, node_id),
            "color": style["color"],
            "glyph": style["glyph"],
            "icon": style.get("icon", "document"),
        }

    def _edge_payload(self, u: str, v: str, k: str, d: dict[str, Any]) -> dict[str, Any]:
        props = {kk: vv for kk, vv in d.items()
                 if kk not in ("type", "tier", "event_time", "ingested_time")}
        return {
            "id": k, "source": u, "target": v, "type": d["type"],
            "tier": d.get("tier", "standard"),
            "event_time": d.get("event_time"),
            "ingested_time": d.get("ingested_time"),
            "props": props,
        }

    # ---------------------------------------------------------- ego networks
    def ego_network(self, node_id: str, hops: int,
                    allowed_tiers: Iterable[str],
                    cap: int | None = None) -> dict[str, Any]:
        """Bounded subgraph around a node (FR-UX-2, FR-GRA-7). Never a full dump."""
        cap = cap or config.MAX_SUBGRAPH_NODES
        vis = self.visible(allowed_tiers)
        if node_id not in vis:
            return {"nodes": [], "edges": [], "truncated": False, "center": node_id}

        und = vis.to_undirected(as_view=True)
        frontier = {node_id}
        seen = {node_id}
        for _ in range(hops):
            nxt: set[str] = set()
            for n in frontier:
                nxt |= set(und.neighbors(n))
            nxt -= seen
            if len(seen) + len(nxt) > cap:
                nxt = set(list(nxt)[: max(0, cap - len(seen))])
                seen |= nxt
                break
            seen |= nxt
            frontier = nxt

        sub = vis.subgraph(seen)
        nodes = [self._node_payload(n, sub.nodes[n]) for n in sub.nodes]
        return {
            "center": node_id,
            "nodes": nodes,
            "edges": [self._edge_payload(u, v, k, d)
                      for u, v, k, d in sub.edges(keys=True, data=True)],
            "max_betweenness": self._attach_centrality(nodes, allowed_tiers),
            "timeline": self.timeline(seen, allowed_tiers),
            "truncated": len(seen) >= cap,
            "cap": cap,
        }

    def path_between(self, src: str, dst: str,
                     allowed_tiers: Iterable[str]) -> dict[str, Any]:
        """Shortest path, used to render the cross-domain chain (FR-GRA-6)."""
        vis = self.visible(allowed_tiers).to_undirected(as_view=True)
        if src not in vis or dst not in vis:
            return {"found": False, "nodes": [], "edges": []}
        try:
            path = nx.shortest_path(vis, src, dst)
        except nx.NetworkXNoPath:
            return {"found": False, "nodes": [], "edges": []}

        full = self.visible(allowed_tiers)
        edges = []
        for a, b in zip(path, path[1:]):
            for u, v in ((a, b), (b, a)):
                if full.has_edge(u, v):
                    k, d = next(iter(full[u][v].items()))
                    edges.append(self._edge_payload(u, v, k, d))
                    break
        nodes = [self._node_payload(n, full.nodes[n]) for n in path]
        return {
            "found": True,
            "nodes": nodes,
            "edges": edges,
            "max_betweenness": self._attach_centrality(nodes, allowed_tiers),
            "timeline": self.timeline(path, allowed_tiers),
            "hops": len(path) - 1,
        }

    # ------------------------------------------------- structural analytics
    def communities_and_bridges(self, allowed_tiers: Iterable[str],
                                cap: int | None = None) -> dict[str, Any]:
        """Louvain communities + Brandes betweenness on a bounded subgraph.

        Super-linear algorithms never run on the whole graph (FR-GRA-7); at this
        scale the bound is not binding, but the policy is enforced in code so it
        still holds when the graph grows.
        """
        cap = cap or config.MAX_SUBGRAPH_NODES
        vis = self.visible(allowed_tiers).to_undirected()

        # Contract SAME_AS first: structural analytics must run on resolved
        # identities, not raw records. Three FIR mentions of one person would
        # otherwise inflate each other's centrality and manufacture a bridge
        # out of nothing but duplicate data entry.
        canonical = self.canonical_map(allowed_tiers)
        simple = nx.Graph()
        for n, d in vis.nodes(data=True):
            c = canonical.get(n, n)
            if c not in simple:
                simple.add_node(c, **vis.nodes[c] if c in vis else d)
        for u, v, d in vis.edges(data=True):
            cu, cv = canonical.get(u, u), canonical.get(v, v)
            if cu != cv and d.get("type") != "SAME_AS":
                simple.add_edge(cu, cv)

        if simple.number_of_nodes() > cap:
            keep = sorted(simple.degree, key=lambda x: -x[1])[:cap]
            simple = simple.subgraph([n for n, _ in keep]).copy()

        comms = nx.community.louvain_communities(
            simple, resolution=config.COMMUNITY_RESOLUTION, seed=42)
        membership = {n: i for i, c in enumerate(comms) for n in c}
        btw = nx.betweenness_centrality(simple, normalized=True)

        # A bridge is a node whose neighbours span several communities: removing
        # it is what actually disconnects the domains (FR-EXP-5).
        spans = {}
        for n in simple.nodes:
            spans[n] = len({membership[m] for m in simple.neighbors(n)})

        # Betweenness ranks the bridge; community span explains why it is one.
        ranked = sorted(simple.nodes, key=lambda n: (btw[n], spans[n]), reverse=True)
        return {
            "n_nodes": simple.number_of_nodes(),
            "n_communities": len(comms),
            "membership": membership,
            "betweenness": btw,
            "community_span": spans,
            "ranked": ranked,
            "bounded_at": cap,
        }

    def invalidate_centrality(self) -> None:
        """Called by anything that changes the shape of the graph."""
        self._centrality_cache.clear()

    def centrality(self, allowed_tiers: Iterable[str]) -> dict[str, Any]:
        """Betweenness and community membership for every visible record.

        Both are computed on resolved identities, so a record is given the
        figure belonging to the identity it resolved into rather than zero -
        otherwise two of the three records behind one person would render as
        peripheral when the person is the bridge.
        """
        key = frozenset(allowed_tiers)
        cached = self._centrality_cache.get(key)
        if cached is not None:
            return cached

        analysis = self.communities_and_bridges(key)
        canonical = self.canonical_map(key)
        btw = analysis["betweenness"]
        membership = analysis["membership"]
        per_node = {}
        for n in self.visible(key).nodes:
            c = canonical.get(n, n)
            per_node[n] = {
                "betweenness": round(btw.get(c, 0.0), 4),
                "community": membership.get(c),
            }
        result = {
            "per_node": per_node,
            "max_betweenness": round(max(btw.values()), 4) if btw else 0.0,
            "n_communities": analysis["n_communities"],
        }
        self._centrality_cache[key] = result
        return result

    def _attach_centrality(self, nodes: list[dict[str, Any]],
                           allowed_tiers: Iterable[str]) -> float:
        """Annotate node payloads in place; returns the network-wide maximum."""
        c = self.centrality(allowed_tiers)
        for n in nodes:
            n.update(c["per_node"].get(n["id"], {"betweenness": 0.0, "community": None}))
        return c["max_betweenness"]

    # -------------------------------------------------------------- timeline
    def timeline(self, node_ids: Iterable[str],
                 allowed_tiers: Iterable[str]) -> list[dict[str, Any]]:
        """Dated events among the given records, in event-time order.

        Only edge types in config.EVENT_EDGE_TYPES are returned. Both times are
        carried through: event time is when it happened, ingestion time is when
        this system learnt of it, and the gap between them is the point.
        """
        ids = set(node_ids)
        vis = self.visible(allowed_tiers)
        events = []
        for u, v, k, d in vis.edges(keys=True, data=True):
            if u not in ids or v not in ids:
                continue
            if d.get("type") not in config.EVENT_EDGE_TYPES:
                continue
            if not d.get("event_time"):
                continue
            events.append({
                "edge_id": k,
                "type": d["type"],
                "event_time": d["event_time"],
                "ingested_time": d.get("ingested_time"),
                "src": u,
                "dst": v,
                "src_display": _display_name(vis.nodes[u], u),
                "dst_display": _display_name(vis.nodes[v], v),
                "src_label": vis.nodes[u].get("label"),
            })
        events.sort(key=lambda e: e["event_time"])
        return events

    def canonical_map(self, allowed_tiers: Iterable[str]) -> dict[str, str]:
        """Map every record to its resolved identity via the SAME_AS closure.

        The canonical record of a group is the lowest id, chosen only so the
        choice is stable. Records are linked rather than collapsed in storage,
        so this mapping is derived on read and a later unmerge simply changes it.
        """
        vis = self.visible(allowed_tiers)
        same = nx.Graph()
        same.add_nodes_from(vis.nodes())
        for u, v, d in vis.edges(data=True):
            if d.get("type") == "SAME_AS":
                same.add_edge(u, v)
        mapping: dict[str, str] = {}
        for comp in nx.connected_components(same):
            head = sorted(comp)[0]
            for n in comp:
                mapping[n] = head
        return mapping

    def resolved_group(self, node_id: str, allowed_tiers: Iterable[str]) -> list[str]:
        canonical = self.canonical_map(allowed_tiers)
        head = canonical.get(node_id, node_id)
        return sorted(n for n, c in canonical.items() if c == head)

    def disconnects_if_removed(self, node_id: str,
                               allowed_tiers: Iterable[str]) -> dict[str, Any]:
        """What breaks if this node is taken out - required for bridge findings."""
        vis = self.visible(allowed_tiers).to_undirected()
        simple = nx.Graph(vis)
        before = nx.number_connected_components(simple)
        if node_id in simple:
            simple.remove_node(node_id)
        after = nx.number_connected_components(simple)
        sizes = sorted((len(c) for c in nx.connected_components(simple)), reverse=True)
        return {
            "components_before": before,
            "components_after": after,
            "splits": after > before,
            "resulting_component_sizes": sizes[:5],
        }

    # -------------------------------------------------------------- search
    def search(self, query: str, allowed_tiers: Iterable[str],
               limit: int | None = None) -> list[dict[str, Any]]:
        """Direct indexed lookup for the emergency path (FR-UX-7).

        Bypasses every queue and every scoring mechanism: it is a retrieval, not
        a detection (principle P1).
        """
        limit = limit or config.EMERGENCY_MAX_RESULTS
        q = _normalise_query(query)
        if not q:
            return []
        vis = self.visible(allowed_tiers)
        hits = []
        for n, d in vis.nodes(data=True):
            for field in ("number", "imei", "registration", "account_no", "name"):
                val = d.get(field)
                if val is None:
                    continue
                if q in _normalise_query(str(val)):
                    hits.append({
                        "node": self._node_payload(n, d),
                        "matched_field": field,
                        "matched_value": val,
                    })
                    break
            if len(hits) >= limit:
                break
        return hits

    def cases_for(self, node_id: str, allowed_tiers: Iterable[str]) -> list[dict[str, Any]]:
        """Every case a node touches, within one hop of an APPEARS_IN edge."""
        vis = self.visible(allowed_tiers)
        if node_id not in vis:
            return []
        out = []
        und = vis.to_undirected(as_view=True)
        for nb in und.neighbors(node_id):
            if vis.nodes[nb].get("label") in ("Case",):
                out.append(self._node_payload(nb, vis.nodes[nb]))
            else:
                for nb2 in und.neighbors(nb):
                    if vis.nodes[nb2].get("label") == "Case":
                        p = self._node_payload(nb2, vis.nodes[nb2])
                        p["via"] = self._node_payload(nb, vis.nodes[nb])["display"]
                        out.append(p)
        seen, uniq = set(), []
        for c in out:
            if c["id"] not in seen:
                seen.add(c["id"])
                uniq.append(c)
        return uniq

    def all_cases(self, allowed_tiers: Iterable[str]) -> list[dict[str, Any]]:
        vis = self.visible(allowed_tiers)
        return [self._node_payload(n, d) for n, d in vis.nodes(data=True)
                if d.get("label") == "Case"]

    def nodes_by_label(self, label: str, allowed_tiers: Iterable[str]) -> list[str]:
        vis = self.visible(allowed_tiers)
        return [n for n, d in vis.nodes(data=True) if d.get("label") == label]

    def stats(self, allowed_tiers: Iterable[str]) -> dict[str, Any]:
        vis = self.visible(allowed_tiers)
        by_label: dict[str, int] = {}
        for _, d in vis.nodes(data=True):
            by_label[d["label"]] = by_label.get(d["label"], 0) + 1
        return {
            "nodes": vis.number_of_nodes(),
            "edges": vis.number_of_edges(),
            "by_label": by_label,
            "transactions": len(self.transactions),
            "merges": len(self.merges),
        }

    # --------------------------------------------------------------- merges
    def apply_merge(self, merge: dict[str, Any]) -> None:
        """Record a SAME_AS link and keep the pre-merge state for reversal.

        Nodes are linked rather than collapsed. That is what makes FR-ER-3
        reversibility cheap: unmerging is removing an edge, not reconstructing
        two records from one.
        """
        self.merges.append(merge)
        self.invalidate_centrality()
        if merge["decision"] != "auto_merge":
            return
        global_key = merge["merge_id"]
        self.g.add_edge(merge["left"], merge["right"], key=f"SAME_AS/{global_key}",
                        type="SAME_AS", tier="standard",
                        event_time=merge["decided_at"],
                        ingested_time=merge["decided_at"],
                        score=merge["score"], basis=merge["basis"],
                        merge_id=global_key)
        self.raw["edges"].append({
            "id": f"SAME_AS/{global_key}", "src": merge["left"],
            "dst": merge["right"], "type": "SAME_AS", "tier": "standard",
            "event_time": merge["decided_at"], "ingested_time": merge["decided_at"],
            "props": {"score": merge["score"], "basis": merge["basis"],
                      "merge_id": global_key},
        })

    def unmerge(self, merge_id: str) -> bool:
        """Reverse a merge (FR-ER-3). Pre-merge state is recoverable by design."""
        key = f"SAME_AS/{merge_id}"
        self.invalidate_centrality()
        removed = False
        for u, v, k in list(self.g.edges(keys=True)):
            if k == key:
                self.g.remove_edge(u, v, key=k)
                removed = True
        self.raw["edges"] = [e for e in self.raw["edges"] if e["id"] != key]
        for m in self.merges:
            if m["merge_id"] == merge_id:
                m["reversed"] = True
        return removed

    def merge_record(self, merge_id: str) -> dict[str, Any] | None:
        for m in self.merges:
            if m["merge_id"] == merge_id:
                return m
        return None


def _display_name(d: dict[str, Any], node_id: str) -> str:
    for key in ("name", "number", "account_no", "registration", "title",
                "description", "bill_of_entry", "line", "doc_type"):
        if d.get(key):
            return str(d[key])
    return node_id


def _normalise_query(s: str) -> str:
    return "".join(ch for ch in s.lower() if ch.isalnum())
