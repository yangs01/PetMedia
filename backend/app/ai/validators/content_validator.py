"""Rule-based marketing integrity checks on AI and human-edited text.

Rules detect claims that need evidence (statistics, certifications, medical
benefits, discounts, warranties, invented testimonials). A flagged phrase is
allowed when it appears in the grounded source facts. These rules catch common
violations but cannot prove a text is fully truthful, so human review remains
the final control.
"""

import re
from typing import Literal

from pydantic import BaseModel

from app.schemas.content import GenerationContext, MasterCopy

Severity = Literal["ERROR", "WARNING"]


class ValidationFinding(BaseModel):
    code: str
    severity: Severity
    message: str
    excerpt: str | None = None


class ValidationReport(BaseModel):
    findings: list[ValidationFinding] = []

    @property
    def has_errors(self) -> bool:
        return any(finding.severity == "ERROR" for finding in self.findings)

    def errors(self) -> list[ValidationFinding]:
        return [finding for finding in self.findings if finding.severity == "ERROR"]

    def to_record(self) -> dict:
        return {"passed": not self.has_errors, **self.model_dump()}

    def as_revision_feedback(self) -> str:
        lines = [f"- {f.message} (found: \"{f.excerpt}\")" for f in self.errors()]
        return "Remove or rewrite these unsupported statements:\n" + "\n".join(lines)


_CLAIM_RULES: list[tuple[str, str, re.Pattern[str]]] = [
    (
        "UNSUPPORTED_SOCIAL_PROOF",
        "Customer popularity or satisfaction claim without source data.",
        re.compile(
            r"\b(thousands|millions|hundreds|tons) of (\w+ )?(customers|owners|parents|buyers|reviews|pets|cats|dogs)\b"
            r"|\b\d[\d,]*\+?\s+(happy|satisfied|loyal)\b"
            r"|\bevery (\w+ )?(owner|parent)s?\b"
            r"|\b\w* ?(owners|parents|customers) (all )?(love|agree|recommend|swear)\b"
            r"|\b(best[- ]selling|bestseller|#1|number one|top[- ]rated|award[- ]winning)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "UNSUPPORTED_STATISTIC",
        "Statistic without source data.",
        re.compile(r"\b\d{1,3}(\.\d+)?\s?% (of|more|less|fewer|better)\b", re.IGNORECASE),
    ),
    (
        "UNSUPPORTED_MEDICAL_CLAIM",
        "Medical or health benefit claim without source data.",
        re.compile(
            r"\b(clinically|scientifically) (proven|tested)\b"
            r"|\b(vet|veterinarian)s?[- ](approved|recommended|tested|endorsed)\b"
            r"|\b(cures?|heals?|treats?|prevents?|relieves?|reduces?|eliminates?) "
            r"(\w+ )?(anxiety|arthritis|disease|illness|obesity|depression|pain|stress|infection|allergies)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "UNSUPPORTED_CERTIFICATION",
        "Certification or safety/material claim that is not in the product data.",
        re.compile(
            r"\b(fda|astm|ce|iso|usda)[- ](approved|certified|compliant|registered)\b"
            r"|\b\w*[- ]?certified\b|\bnon[- ]toxic\b|\bbpa[- ]free\b|\bfood[- ]grade\b"
            r"|\bhypoallergenic\b|\beco[- ]friendly\b|\borganic\b|\bbiodegradable\b"
            r"|\bindestructible\b|\b100% safe\b|\bcompletely safe\b",
            re.IGNORECASE,
        ),
    ),
    (
        "UNSUPPORTED_OFFER",
        "Discount, offer or warranty that is not in the product data.",
        re.compile(
            r"\b\d{1,3}% off\b|\bdiscount(s|ed)?\b|\bfree shipping\b|\blimited[- ]time\b"
            r"|\bwarrant(y|ies)\b|\bmoney[- ]back\b|\bguarantee(s|d)?\b|\blifetime\b",
            re.IGNORECASE,
        ),
    ),
    (
        "IMPERSONATED_EXPERIENCE",
        "First-person customer experience that may impersonate a real customer.",
        re.compile(
            r"\bmy (cat|dog|kitten|puppy|pet|pup|kitty)\b"
            r"|\b(i|we) (bought|tried|purchased|ordered|have used|have been using)\b",
            re.IGNORECASE,
        ),
    ),
]

_NON_ENGLISH = re.compile(r"[Ѐ-ӿ֐-ۿ぀-ヿ㐀-鿿가-힯]+")
_QUOTED = re.compile(r"[\"“]([^\"“”]{20,})[\"”]")


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def grounding_text(context: GenerationContext) -> str:
    """All text a claim may legitimately come from."""
    parts = [context.brand.brand_description or ""]
    for product in context.products:
        parts += [
            product.name,
            product.description,
            product.usage_instructions or "",
            product.safety_notes or "",
            *product.key_features,
            *product.materials,
            *product.suitable_pets,
        ]
    parts += [review.review_text for review in context.reviews]
    return _normalize("\n".join(parts))


def validate_text(text: str, context: GenerationContext) -> ValidationReport:
    findings: list[ValidationFinding] = []
    source = grounding_text(context)

    for code, message, pattern in _CLAIM_RULES:
        for match in pattern.finditer(text):
            if _normalize(match.group(0)) not in source:
                findings.append(
                    ValidationFinding(code=code, severity="ERROR", message=message, excerpt=match.group(0))
                )

    lowered = _normalize(text)
    for claim in context.brand.prohibited_claims:
        if claim.strip() and _normalize(claim) in lowered:
            findings.append(
                ValidationFinding(
                    code="PROHIBITED_CLAIM",
                    severity="ERROR",
                    message="The brand profile prohibits this claim.",
                    excerpt=claim,
                )
            )

    foreign = _NON_ENGLISH.search(text)
    if foreign:
        findings.append(
            ValidationFinding(
                code="NON_ENGLISH_TEXT",
                severity="ERROR",
                message="Generated content must be in English.",
                excerpt=foreign.group(0)[:50],
            )
        )

    for match in _QUOTED.finditer(text):
        if _normalize(match.group(1)) not in source:
            findings.append(
                ValidationFinding(
                    code="UNTRACEABLE_QUOTE",
                    severity="WARNING",
                    message="Quoted text does not match any authorized customer review.",
                    excerpt=match.group(1)[:120],
                )
            )
    return ValidationReport(findings=findings)


def validate_master_copy(copy: MasterCopy, context: GenerationContext) -> ValidationReport:
    report = validate_text(copy.full_text(), context)
    known_products = {product.id for product in context.products}
    known_reviews = {review.id for review in context.reviews}

    unknown_products = set(copy.featured_product_ids) - known_products
    if unknown_products:
        report.findings.append(
            ValidationFinding(
                code="UNKNOWN_PRODUCT",
                severity="ERROR",
                message="The draft references a product that is not part of this task.",
                excerpt=", ".join(sorted(unknown_products)),
            )
        )
    unknown_reviews = set(copy.source_review_ids) - known_reviews
    if unknown_reviews:
        report.findings.append(
            ValidationFinding(
                code="UNKNOWN_REVIEW",
                severity="ERROR",
                message="The draft cites a review that is not an authorized source.",
                excerpt=", ".join(sorted(unknown_reviews)),
            )
        )

    word_count = len(copy.body.split())
    if word_count < context.target_word_count * 0.5 or word_count > context.target_word_count * 1.5:
        report.findings.append(
            ValidationFinding(
                code="WORD_COUNT_OUT_OF_RANGE",
                severity="WARNING",
                message=f"Body has {word_count} words; the target is {context.target_word_count}.",
            )
        )
    return report
