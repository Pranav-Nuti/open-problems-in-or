/**
 * Client-side problem search via MiniSearch (loaded from CDN in index.html).
 */
(function () {
  function requireMiniSearch() {
    if (typeof MiniSearch === "undefined") {
      throw new Error("MiniSearch did not load; check the CDN script in index.html.");
    }
    return MiniSearch;
  }

  function documentForProblem(p) {
    return {
      id: p.problem_id,
      problemId: String(p.problem_id ?? ""),
      title: String(p.title ?? ""),
      area: String(p.__area ?? ""),
      category: String(p.__category ?? ""),
      keywords: Array.isArray(p.keywords) ? p.keywords.join(" ") : "",
      paper: [p.source_paper_title, p.source_paper, p.source_paper_journal]
        .map((v) => String(v ?? ""))
        .filter(Boolean)
        .join(" "),
      authors: Array.isArray(p.source_paper_authors) ? p.source_paper_authors.join(" ") : "",
      attempt: `${p.__attemptLabel ?? ""} ${p.__attemptSearch ?? ""}`.trim(),
    };
  }

  function buildIndex(problems) {
    const MiniSearchCtor = requireMiniSearch();
    const miniSearch = new MiniSearchCtor({
      fields: ["title", "area", "category", "keywords", "paper", "authors", "attempt", "problemId"],
      storeFields: ["problemId"],
      searchOptions: {
        prefix: true,
        fuzzy: 0.2,
        boost: { title: 2, area: 1.5, category: 1.2 },
      },
    });
    miniSearch.addAll(problems.map(documentForProblem));
    return miniSearch;
  }

  /** @returns {Set<string>|null} problem_id set when query is non-empty; null means no text filter */
  function matchingIds(miniSearch, query) {
    const trimmed = String(query ?? "").trim();
    if (!trimmed) {
      return null;
    }
    const hits = miniSearch.search(trimmed, { combineWith: "AND" });
    return new Set(hits.map((hit) => hit.id));
  }

  window.ProblemSearch = Object.freeze({
    buildIndex,
    matchingIds,
  });
})();
