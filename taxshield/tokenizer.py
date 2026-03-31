"""Token allocation for names and identifiers.

Same real name across different forms gets the same token.
"""

from dataclasses import dataclass, field


@dataclass
class TokenMap:
    """Manages token allocation and mapping."""
    _name_to_token: dict[str, str] = field(default_factory=dict)
    _token_to_name: dict[str, str] = field(default_factory=dict)
    _counters: dict[str, int] = field(default_factory=lambda: {
        "Taxpayer": 0,
        "Spouse": 0,
        "Dependent": 0,
        "Employer": 0,
        "Parent": 0,
        "Broker": 0,
    })
    _same_as: dict[str, str] = field(default_factory=dict)

    def _normalize(self, name: str) -> str:
        """Normalize name for comparison (lowercase, strip whitespace)."""
        return " ".join(name.lower().split())

    def get_or_create_token(self, name: str, role: str) -> str:
        """Get existing token for a name, or create a new one.

        Args:
            name: The real name/identifier.
            role: One of "Taxpayer", "Spouse", "Dependent", "Employer", "Parent", "Broker".

        Returns:
            The token string, e.g., "Employer-1".
        """
        normalized = self._normalize(name)

        if normalized in self._name_to_token:
            existing_token = self._name_to_token[normalized]
            # If this name already has a token from a different role,
            # record the cross-role relationship
            if not existing_token.startswith(role):
                new_token = self._create_new_token(role)
                self._same_as[new_token] = existing_token
                self._same_as[existing_token] = new_token
            return existing_token

        token = self._create_new_token(role)
        self._name_to_token[normalized] = token
        self._token_to_name[token] = name
        return token

    def _create_new_token(self, role: str) -> str:
        """Create a new token with the given role prefix."""
        if role not in self._counters:
            self._counters[role] = 0
        self._counters[role] += 1
        count = self._counters[role]
        if role == "Taxpayer":
            suffix = chr(ord('A') + count - 1) if count <= 26 else str(count)
            return f"Taxpayer-{suffix}"
        elif role == "Spouse":
            suffix = chr(ord('A') + count - 1) if count <= 26 else str(count)
            return f"Spouse-{suffix}"
        else:
            return f"{role}-{count}"

    def lookup_token(self, name: str) -> str | None:
        """Look up if a name already has a token."""
        normalized = self._normalize(name)
        return self._name_to_token.get(normalized)

    def get_all_mappings(self) -> list[dict]:
        """Return all token mappings for writing to map files.

        Returns:
            List of dicts with keys: token, original, note.
        """
        results = []
        for token, original in sorted(self._token_to_name.items()):
            note = ""
            if token in self._same_as:
                note = f"same_as:{self._same_as[token]}"
            results.append({
                "token": token,
                "original": original,
                "note": note,
            })
        return results
