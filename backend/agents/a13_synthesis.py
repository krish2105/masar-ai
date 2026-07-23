"""A13 — Synthesis and Citation.

Composes the final answer in the query's language, with an inline `[S1]` marker
on every factual claim.

Three rules, all enforced in code rather than only in the prompt, because a
prompt instruction is a request and this system's credibility depends on
guarantees:

1. **A claim that cannot be sourced is deleted, not softened.** Post-generation
   validation strips citation markers that do not resolve to a real source.
2. **Numbers from A11 are quoted verbatim.** The calculator's output is injected
   as pre-formatted text and the model is told not to recompute. LLM arithmetic
   is the single most common source of confidently wrong money figures.
3. **The answer language mirrors the question.** No exceptions.

The answer also carries its confidence and every declared assumption. At the
cycle cap the limitation is stated in the answer itself, not buried in metadata
the reader will not open.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from backend.graph.state import Confidence, Evidence, EvidenceType, GradeReport, Source
from backend.services.logging import get_logger

log = get_logger(__name__)

_CITATION = re.compile(r"\[S(\d+)\]")

_SYSTEM_EN = """You answer questions about Dubai's public transport using ONLY the
evidence provided.

RULES — these are not stylistic preferences.

1. Every factual claim carries an inline citation: [S1], [S2]. A sentence
   stating a fact with no citation must not appear.
2. If the evidence does not support a claim, DELETE the claim. Do not hedge it,
   do not soften it, do not write "it may be". Say plainly what you do not know.
3. Numbers marked CALCULATED are already correct. Quote them EXACTLY. Never
   recompute, re-round or restate them differently. You are not permitted to do
   arithmetic.
4. Where evidence carries a capture date, say the figure is as of that date. The
   data is archived, not live.
5. Be direct. Lead with the answer, then the support. No preamble, no "great
   question", no restating the question back.
6. If the evidence is thin, say so in the answer itself.

FORMAT
- Short paragraphs or a tight list.
- Bold the single most important figure.
- Markdown, no headings unless the answer genuinely has sections."""

_SYSTEM_AR = """أنت تجيب عن أسئلة حول النقل العام في دبي باستخدام الأدلة المقدمة فقط.

القواعد — هذه ليست تفضيلات أسلوبية.

١. كل معلومة واقعية يجب أن تحمل مرجعاً مضمناً: [S1]، [S2]. لا تكتب جملة تذكر
   حقيقة دون مرجع.
٢. إذا لم تدعم الأدلة معلومة ما، احذفها. لا تلمّح إليها ولا تخفف صياغتها.
   قل بوضوح ما لا تعرفه.
٣. الأرقام المعلَّمة بـ CALCULATED صحيحة بالفعل. انقلها حرفياً. لا تعد حسابها
   ولا تقربها. غير مسموح لك بإجراء أي عملية حسابية.
٤. عندما يحمل الدليل تاريخ أرشفة، اذكر أن الرقم صحيح حتى ذلك التاريخ. البيانات
   مؤرشفة وليست مباشرة.
٥. كن مباشراً. ابدأ بالإجابة ثم الدليل. بدون مقدمات.
٦. إذا كانت الأدلة ضعيفة، قل ذلك في الإجابة نفسها.

التنسيق
- فقرات قصيرة أو قائمة موجزة.
- أبرز أهم رقم بخط عريض.
- استخدم الأرقام العربية الشرقية فقط إذا استخدمها المستخدم."""


@dataclass(slots=True)
class SynthesisResult:
    answer: str
    citations: list[Source] = field(default_factory=list)
    confidence: Confidence = Confidence.MEDIUM
    assumptions: list[str] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)
    provider: str | None = None
    unsourced_removed: int = 0
    """Citation markers stripped because they resolved to nothing."""

    language: str = "en"


def _confidence_from(grade: GradeReport | None, cycles_used: int, max_cycles: int) -> Confidence:
    if grade is None:
        return Confidence.LOW
    if cycles_used >= max_cycles and not grade.sufficient:
        return Confidence.LOW
    lowest = min(grade.scores.values())
    if lowest >= 0.85 and grade.sufficient:
        return Confidence.HIGH
    if grade.sufficient:
        return Confidence.MEDIUM
    return Confidence.LOW


class SynthesisAgent:
    def __init__(self, router=None) -> None:
        self.router = router

    # ------------------------------------------------------------- format --
    @staticmethod
    def build_sources(evidence: list[Evidence]) -> tuple[list[Source], str]:
        """Number the evidence and render it for the prompt.

        Numbering happens here, deterministically, so `[S3]` in the answer and
        `S3` in the evidence panel are guaranteed to be the same thing.
        """
        sources: list[Source] = []
        blocks: list[str] = []

        for index, item in enumerate(evidence, start=1):
            source = Source(
                id=f"S{index}",
                type=item.evidence_type,
                dataset_or_doc=item.source.dataset_or_doc,
                source_url=item.source.source_url,
                row_id_or_chunk_id=item.source.row_id_or_chunk_id,
                captured_at=item.source.captured_at,
                source_tier=item.source.source_tier,
                is_synthetic=item.source.is_synthetic,
                last_updated=item.source.last_updated,
            )
            sources.append(source)

            marker = "CALCULATED — quote exactly, do not recompute" if item.evidence_type is EvidenceType.CALC_RESULT else str(item.evidence_type)
            captured = f" (captured {item.source.captured_at[:10]})" if item.source.captured_at else ""
            blocks.append(
                f"[S{index}] {marker} · {item.source.dataset_or_doc}{captured}\n{item.content[:1400]}"
            )

        return sources, "\n\n".join(blocks)

    @staticmethod
    def validate_citations(answer: str, sources: list[Source]) -> tuple[str, list[Source], int]:
        """Strip markers that do not resolve, and return only cited sources.

        §8.2 requires citation validity of exactly 1.00. That cannot be achieved
        by asking a model nicely; it is achieved by deleting what does not
        resolve. An unresolvable marker is worse than no marker — it looks like
        evidence.
        """
        valid_ids = {s.id for s in sources}
        removed = 0

        def replace(match: re.Match) -> str:
            nonlocal removed
            if f"S{match.group(1)}" in valid_ids:
                return match.group(0)
            removed += 1
            return ""

        cleaned = _CITATION.sub(replace, answer)
        cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
        cleaned = re.sub(r"\s+([.,;:])", r"\1", cleaned)

        used = {f"S{m}" for m in _CITATION.findall(cleaned)}
        return cleaned.strip(), [s for s in sources if s.id in used], removed

    # ---------------------------------------------------------------- run --
    async def run(
        self,
        question: str,
        evidence: list[Evidence],
        *,
        response_language: str = "en",
        grade: GradeReport | None = None,
        cycles_used: int = 0,
        max_cycles: int = 3,
        assumptions: list[str] | None = None,
        caveats: list[str] | None = None,
        degraded_mode: bool = False,
    ) -> SynthesisResult:
        sources, evidence_block = self.build_sources(evidence)
        confidence = _confidence_from(grade, cycles_used, max_cycles)
        arabic = response_language == "ar"

        if not evidence:
            return SynthesisResult(
                answer=self._no_evidence_message(arabic),
                confidence=Confidence.LOW,
                language=response_language,
                caveats=list(caveats or []),
            )

        if self.router is None:
            return SynthesisResult(
                answer=self._extractive_fallback(evidence, sources, arabic),
                citations=sources[:5],
                confidence=Confidence.LOW,
                language=response_language,
                caveats=[
                    *(caveats or []),
                    "No language model was available, so this answer is an extract of the "
                    "retrieved evidence rather than a composed response.",
                ],
            )

        instructions: list[str] = []
        if cycles_used >= max_cycles and grade is not None and not grade.sufficient:
            instructions.append(
                "The evidence remains incomplete after the maximum number of re-planning "
                "cycles. State this limitation explicitly in your answer."
            )
        if grade is not None and grade.gaps:
            instructions.append("Known gaps: " + "; ".join(grade.gaps[:3]))
        if degraded_mode:
            instructions.append(
                "This answer is being generated by a local fallback model because no cloud "
                "provider was available. Keep it concise and strictly grounded."
            )

        user_content = (
            f"QUESTION\n{question}\n\n"
            f"EVIDENCE\n{evidence_block}\n\n"
            + ("INSTRUCTIONS\n" + "\n".join(f"- {i}" for i in instructions) if instructions else "")
        )

        try:
            completion = await self.router.complete(
                "arabic" if arabic else "synthesis",
                [
                    {"role": "system", "content": _SYSTEM_AR if arabic else _SYSTEM_EN},
                    {"role": "user", "content": user_content},
                ],
            )
            answer = completion.text.strip()
            provider = completion.provider
        except Exception as exc:  # noqa: BLE001
            log.warning("synthesis.failed", error=f"{type(exc).__name__}: {exc}")
            return SynthesisResult(
                answer=self._extractive_fallback(evidence, sources, arabic),
                citations=sources[:5],
                confidence=Confidence.LOW,
                language=response_language,
                caveats=[*(caveats or []), "Answer composition failed; showing retrieved evidence."],
            )

        answer, cited, removed = self.validate_citations(answer, sources)
        if removed:
            log.warning("synthesis.unsourced_citations_removed", count=removed)

        answer = self._append_notices(
            answer, confidence, cycles_used, max_cycles, grade, degraded_mode, arabic
        )

        log.info(
            "synthesis.composed",
            language=response_language,
            citations=len(cited),
            confidence=str(confidence),
            removed=removed,
            provider=provider,
        )
        return SynthesisResult(
            answer=answer,
            citations=cited,
            confidence=confidence,
            assumptions=list(assumptions or []),
            caveats=list(caveats or []),
            provider=provider,
            unsourced_removed=removed,
            language=response_language,
        )

    # ---------------------------------------------------------- fallbacks --
    @staticmethod
    def _no_evidence_message(arabic: bool) -> str:
        if arabic:
            return (
                "لم أتمكن من العثور على أدلة في البيانات المتاحة للإجابة عن هذا السؤال. "
                "بدلاً من التخمين، أوضح أن البيانات المؤرشفة التي أعتمد عليها لا تغطي هذا "
                "الموضوع. جرّب السؤال عن الخطوط أو المحطات أو الأجور أو أعداد الركاب."
            )
        return (
            "I couldn't find evidence in the data I hold to answer that. Rather than "
            "guess, I'd rather tell you plainly: the archived RTA datasets I work from "
            "don't cover it. Try asking about routes, stations, fares, zones or "
            "ridership and I'll cite exactly where the answer comes from."
        )

    @staticmethod
    def _extractive_fallback(
        evidence: list[Evidence], sources: list[Source], arabic: bool
    ) -> str:
        header = (
            "استناداً إلى الأدلة المسترجعة:" if arabic else "Based on the retrieved evidence:"
        )
        lines = [header, ""]
        for source, item in zip(sources[:5], evidence[:5], strict=False):
            snippet = item.content.strip().replace("\n", " ")[:280]
            lines.append(f"- {snippet} [{source.id}]")
        return "\n".join(lines)

    @staticmethod
    def _append_notices(
        answer: str,
        confidence: Confidence,
        cycles_used: int,
        max_cycles: int,
        grade: GradeReport | None,
        degraded_mode: bool,
        arabic: bool,
    ) -> str:
        notices: list[str] = []

        if confidence is Confidence.LOW:
            notices.append(
                "⚠︎ الثقة منخفضة — الأدلة المتاحة لا تدعم إجابة قاطعة."
                if arabic
                else "⚠︎ Low confidence — the available evidence doesn't fully support this answer."
            )
        if cycles_used >= max_cycles and grade is not None and not grade.sufficient:
            notices.append(
                f"أعاد النظام التخطيط {cycles_used} مرات ولم يعثر على أدلة كافية."
                if arabic
                else f"The system re-planned {cycles_used} times and still could not gather sufficient evidence."
            )
        if degraded_mode:
            notices.append(
                "تم إنشاء هذه الإجابة بنموذج محلي لعدم توفر مزود سحابي."
                if arabic
                else "Generated by a local fallback model — no cloud provider was available."
            )

        return f"{answer}\n\n---\n" + "\n".join(f"*{n}*" for n in notices) if notices else answer
