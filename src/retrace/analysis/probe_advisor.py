"""
Bayesian probe point advisor for PCB reverse engineering.

Given a set of detected components and any measurements already taken,
recommends the next probe point that maximises information gain as measured
by Shannon entropy reduction over the hypothesis space.

The hypothesis space is the set of possible net assignments for each unknown
node.  A Dirichlet-backed probability distribution is maintained over each
candidate net label.  Information gain for a candidate probe point is
approximated as the expected reduction in entropy across all nodes that share
a net with that point under the current belief state.

No external dependencies beyond numpy.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class Component:
    """A component detected on the board."""
    ref: str                        # e.g. "U1", "R12"
    kind: str                       # e.g. "IC", "resistor", "capacitor"
    pins: list[str]                 # pin names, e.g. ["VCC","GND","OUT"]
    location: tuple[float, float]   # (x, y) in image-space pixels


@dataclass
class ProbePoint:
    """A candidate probe location on the board."""
    node_id: str                    # unique identifier, e.g. "U1.VCC"
    location: tuple[float, float]   # (x, y) pixels
    component_ref: str
    pin_name: str


@dataclass
class Measurement:
    """A measurement taken at a probe point."""
    node_id: str
    voltage: float | None = None
    resistance: float | None = None
    continuity_to: str | None = None  # node_id of node that rings out


@dataclass
class Recommendation:
    """Output of the advisor: a ranked list of probe points."""
    node_id: str
    location: tuple[float, float]
    expected_info_gain: float       # bits
    rationale: str


# ---------------------------------------------------------------------------
# Core class
# ---------------------------------------------------------------------------

class ProbeAdvisor:
    """
    Bayesian advisor that recommends probe points for maximum information gain.

    Internally maintains a belief distribution P(net_label | node) for every
    unknown node.  Net labels are drawn from a vocabulary that grows as
    measurements are taken.

    Parameters
    ----------
    net_labels : list[str]
        Initial vocabulary of net names to consider (e.g. ["VCC","GND","NET1"]).
        Automatically extended when continuity measurements reveal new nets.
    alpha : float
        Dirichlet concentration parameter (pseudo-count).  Lower = more
        sensitive to measurements; higher = more sceptical prior.
    """

    def __init__(
        self,
        net_labels: list[str] | None = None,
        alpha: float = 1.0,
    ) -> None:
        self._labels: list[str] = list(net_labels or ["VCC", "GND", "NET_UNKNOWN"])
        self._alpha = alpha

        # node_id -> Dirichlet counts array (len == number of net labels)
        self._counts: dict[str, np.ndarray] = {}

        # node_id -> ProbePoint metadata
        self._nodes: dict[str, ProbePoint] = {}

        # already-measured nodes (their entropy is 0 — collapsed to known net)
        self._resolved: dict[str, str] = {}  # node_id -> net_label

        # continuity groups: union-find parent map
        self._parent: dict[str, str] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add_components(self, components: list[Component]) -> None:
        """Register components and initialise probe point nodes."""
        for comp in components:
            for pin in comp.pins:
                node_id = f"{comp.ref}.{pin}"
                pp = ProbePoint(
                    node_id=node_id,
                    location=comp.location,
                    component_ref=comp.ref,
                    pin_name=pin,
                )
                self._nodes[node_id] = pp
                if node_id not in self._counts:
                    self._counts[node_id] = np.full(len(self._labels), self._alpha)
                self._parent[node_id] = node_id

        # Apply domain knowledge priors based on pin names
        self._apply_pin_name_priors()

    def recommend(
        self,
        image_path: str | None = None,
        top_k: int = 5,
    ) -> list[Recommendation]:
        """
        Return the top-k probe points ranked by expected information gain.

        Parameters
        ----------
        image_path : str, optional
            Reserved for future use (e.g. CV-based patch analysis).
            Currently ignored — the advisor operates on structural priors only.
        top_k : int
            Number of recommendations to return.

        Returns
        -------
        list[Recommendation]
            Sorted descending by expected_info_gain (bits).
        """
        candidates: list[Recommendation] = []

        for node_id, pp in self._nodes.items():
            if node_id in self._resolved:
                continue  # already known — skip

            root = self._find(node_id)
            eig = self._expected_info_gain(root)
            rationale = self._build_rationale(node_id, eig)
            candidates.append(
                Recommendation(
                    node_id=node_id,
                    location=pp.location,
                    expected_info_gain=eig,
                    rationale=rationale,
                )
            )

        candidates.sort(key=lambda r: r.expected_info_gain, reverse=True)
        return candidates[:top_k]

    def update(self, probe_point: str, measurement: Measurement) -> None:
        """
        Incorporate a new measurement and update beliefs.

        Parameters
        ----------
        probe_point : str
            node_id that was probed.
        measurement : Measurement
            The observed measurement at that node.
        """
        if probe_point not in self._nodes:
            raise ValueError(f"Unknown probe point: {probe_point!r}")

        net_label = self._measurement_to_label(measurement)

        if net_label not in self._labels:
            # Extend vocabulary
            self._labels.append(net_label)
            for nid in self._counts:
                self._counts[nid] = np.append(self._counts[nid], self._alpha)

        label_idx = self._labels.index(net_label)

        # Collapse the probed node's distribution to this label
        root = self._find(probe_point)
        counts = np.zeros(len(self._labels))
        counts[label_idx] = 1e6  # near-certain
        self._counts[root] = counts
        self._resolved[probe_point] = net_label

        # If a continuity pair was given, merge the two nodes
        if measurement.continuity_to is not None:
            other = measurement.continuity_to
            if other in self._nodes:
                self._union(probe_point, other)
                self._resolved[other] = net_label

        # Propagate: any node whose root is now resolved gets updated too
        for nid in list(self._counts.keys()):
            r = self._find(nid)
            if r in self._resolved and nid not in self._resolved:
                self._resolved[nid] = self._resolved[r]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _entropy(self, node_id: str) -> float:
        """Shannon entropy (bits) of belief distribution for node_id."""
        counts = self._counts.get(node_id, np.full(len(self._labels), self._alpha))
        probs = counts / counts.sum()
        # Avoid log(0)
        nonzero = probs[probs > 0]
        return float(-np.sum(nonzero * np.log2(nonzero)))

    def _expected_info_gain(self, root: str) -> float:
        """
        Approximate EIG for probing the given root node.

        We approximate by computing the current entropy (the gain if we
        resolve this node with certainty) minus a small residual term that
        accounts for the uncertainty in what label we will actually observe.
        This is equivalent to the mutual information I(Label; Measurement).
        """
        H_prior = self._entropy(root)
        if H_prior < 1e-9:
            return 0.0

        counts = self._counts.get(root, np.full(len(self._labels), self._alpha))
        probs = counts / counts.sum()

        # Expected posterior entropy: E_y[H(p | y)] where y is the outcome.
        # For each possible outcome y (label), posterior is near-zero everywhere
        # except at y — so posterior entropy ~ 0.  Therefore EIG ~ H_prior.
        # We add a small correction for label ambiguity.
        label_H = -float(np.sum(probs[probs > 0] * np.log2(probs[probs > 0])))
        eig = H_prior - (H_prior - label_H) * 0.1  # 10% residual
        return max(0.0, eig)

    def _apply_pin_name_priors(self) -> None:
        """
        Boost the probability of well-known net labels based on pin names.
        """
        power_pins = {"vcc", "vdd", "v+", "power", "3v3", "5v", "vin", "vbat"}
        ground_pins = {"gnd", "vss", "agnd", "pgnd", "v-", "ground", "sg"}

        for node_id, pp in self._nodes.items():
            if node_id in self._resolved:
                continue
            pname = pp.pin_name.lower().strip()

            if pname in power_pins:
                self._boost_label(node_id, "VCC", factor=10.0)
            elif pname in ground_pins:
                self._boost_label(node_id, "GND", factor=10.0)

    def _boost_label(self, node_id: str, label: str, factor: float) -> None:
        if label not in self._labels:
            self._labels.append(label)
            for nid in self._counts:
                self._counts[nid] = np.append(self._counts[nid], self._alpha)
        if node_id not in self._counts:
            self._counts[node_id] = np.full(len(self._labels), self._alpha)
        idx = self._labels.index(label)
        # Ensure array length matches current label count
        if len(self._counts[node_id]) < len(self._labels):
            diff = len(self._labels) - len(self._counts[node_id])
            self._counts[node_id] = np.append(
                self._counts[node_id], np.full(diff, self._alpha)
            )
        self._counts[node_id][idx] *= factor

    def _measurement_to_label(self, m: Measurement) -> str:
        """Convert a raw measurement to a net label string."""
        if m.continuity_to is not None:
            # Follow to the resolved net if known
            other_root = self._find(m.continuity_to)
            if other_root in self._resolved:
                return self._resolved[other_root]
            return f"NET_{m.continuity_to}"
        if m.voltage is not None:
            if m.voltage > 4.5:
                return "VCC"
            if m.voltage < 0.3:
                return "GND"
            v_rounded = round(m.voltage * 10) / 10
            return f"NET_{v_rounded}V"
        if m.resistance is not None:
            if m.resistance < 5.0:
                return "GND"
        return "NET_UNKNOWN"

    def _build_rationale(self, node_id: str, eig: float) -> str:
        root = self._find(node_id)
        counts = self._counts.get(root, np.full(len(self._labels), self._alpha))
        probs = counts / counts.sum()
        top_idx = int(np.argmax(probs))
        top_label = self._labels[top_idx]
        top_prob = float(probs[top_idx])
        return (
            f"EIG={eig:.3f} bits; most likely net: {top_label} ({top_prob:.1%}). "
            f"Probing {node_id} will resolve ~{eig:.2f} bits of uncertainty."
        )

    # ------------------------------------------------------------------
    # Union-Find for continuity groups
    # ------------------------------------------------------------------

    def _find(self, node_id: str) -> str:
        if node_id not in self._parent:
            self._parent[node_id] = node_id
        if self._parent[node_id] != node_id:
            self._parent[node_id] = self._find(self._parent[node_id])
        return self._parent[node_id]

    def _union(self, a: str, b: str) -> None:
        ra, rb = self._find(a), self._find(b)
        if ra == rb:
            return
        # Merge rb into ra (keep ra as root)
        self._parent[rb] = ra
        # Merge counts: take the more informed distribution
        ca = self._counts.get(ra, np.full(len(self._labels), self._alpha))
        cb = self._counts.get(rb, np.full(len(self._labels), self._alpha))
        # Align lengths
        n = max(len(ca), len(cb))
        if len(ca) < n:
            ca = np.append(ca, np.full(n - len(ca), self._alpha))
        if len(cb) < n:
            cb = np.append(cb, np.full(n - len(cb), self._alpha))
        self._counts[ra] = ca + cb - self._alpha  # combine, subtract shared prior


# ---------------------------------------------------------------------------
# CLI / standalone demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":  # pragma: no cover
    print("ProbeAdvisor — standalone demo")

    advisor = ProbeAdvisor(net_labels=["VCC", "GND", "NET_A", "NET_B"])

    components = [
        Component("U1", "IC", ["VCC", "GND", "OUT", "IN"], (100.0, 200.0)),
        Component("R1", "resistor", ["1", "2"], (300.0, 150.0)),
        Component("C1", "capacitor", ["VCC", "GND"], (400.0, 300.0)),
    ]
    advisor.add_components(components)

    print("\nInitial recommendations (top 5):")
    for rec in advisor.recommend(top_k=5):
        print(f"  {rec.node_id:15s}  EIG={rec.expected_info_gain:.3f} bits  {rec.rationale}")

    # Simulate probing U1.VCC and finding it is 3.3 V
    advisor.update("U1.VCC", Measurement("U1.VCC", voltage=3.3))

    print("\nAfter measuring U1.VCC = 3.3V:")
    for rec in advisor.recommend(top_k=5):
        print(f"  {rec.node_id:15s}  EIG={rec.expected_info_gain:.3f} bits  {rec.rationale}")

    # Simulate probing U1.GND and finding continuity to C1.GND
    advisor.update("U1.GND", Measurement("U1.GND", continuity_to="C1.GND"))

    print("\nAfter finding U1.GND rings out to C1.GND:")
    for rec in advisor.recommend(top_k=5):
        print(f"  {rec.node_id:15s}  EIG={rec.expected_info_gain:.3f} bits  {rec.rationale}")
