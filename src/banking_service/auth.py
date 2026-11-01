"""Offline verification of operator-provisioned platform JWKS, never caller URLs."""
from dataclasses import dataclass
import json
from pathlib import Path

import jwt

from src.banking_contracts.codec import ContractError


@dataclass(frozen=True)
class ActorIdentity:
    atespace: str
    name: str
    uid: str


class IdentityVerifier:
    def __init__(self, config):
        self.config = config
        self.keys = {}
        for kind in ("driver", "actor"):
            keys = {}
            for value in config[kind]["jwks"]["keys"]:
                # K8s JWK sets may omit alg. Infer only from these two public types.
                algorithm = value.get("alg") or {"RSA": "RS256", "EC": "ES256"}.get(value.get("kty"))
                if algorithm not in {"RS256", "ES256"}: raise ValueError("unsupported_platform_key")
                if not value.get("kid") or value["kid"] in keys: raise ValueError("ambiguous_platform_key")
                keys[value["kid"]] = (jwt.PyJWK.from_dict(value, algorithm=algorithm), algorithm)
            self.keys[kind] = keys

    @classmethod
    def from_file(cls, path): return cls(json.loads(Path(path).read_text()))

    def _decode(self, authorization, kind):
        if not isinstance(authorization, str) or not authorization.startswith("Bearer ") or len(authorization) > 16384:
            raise ContractError("unauthenticated", "authentication")
        token = authorization[7:]
        try:
            header = jwt.get_unverified_header(token)
            key, algorithm = self.keys[kind][header["kid"]]
            if header.get("alg") != algorithm: raise ValueError("unexpected_algorithm")
            config = self.config[kind]
            return jwt.decode(token, key.key, algorithms=[algorithm], issuer=config["issuer"],
                audience=config["audience"], options={"require": ["iss", "aud", "exp", "iat", "sub"]})
        except (jwt.PyJWTError, KeyError, ValueError, TypeError):
            raise ContractError("unauthenticated", "authentication") from None

    def driver(self, authorization):
        claims = self._decode(authorization, "driver")
        if claims["sub"] != self.config["driver"]["subject"]:
            raise ContractError("driver_not_allowed", "authentication")
        return claims["sub"]

    def actor(self, authorization):
        claims = self._decode(authorization, "actor")
        identity = claims.get("actor.ate.dev")
        if not isinstance(identity, dict) or claims.get("worker-for-actor.ate.dev") is not None:
            raise ContractError("actor_identity_required", "authentication")
        fields = [identity.get(k) for k in ("atespace", "actorName", "actorUID")]
        if (any(not isinstance(v, str) or not v or len(v) > 128 for v in fields) or identity.get("node") or
                identity["atespace"] != self.config["actor"]["atespace"] or
                claims["sub"] != f"actor/{fields[0]}/{fields[1]}"):
            raise ContractError("actor_identity_required", "authentication")
        return ActorIdentity(*fields)
