(() => {
  const root = document.querySelector("[data-live-search]");
  if (!root) return;

  const form = root.querySelector("[data-live-search-form]");
  const state = root.querySelector("[data-live-search-state]");
  const resultsRoot = root.querySelector("[data-live-results]");
  const actions = root.querySelector("[data-live-search-actions]");
  const bibtexButton = root.querySelector("[data-live-bibtex]");
  let currentResults = [];

  const text = (tag, value, className = "") => {
    const node = document.createElement(tag);
    node.textContent = value || "";
    if (className) node.className = className;
    return node;
  };

  const reconstructAbstract = (inverted) => {
    if (!inverted) return "暂无摘要";
    const words = [];
    Object.entries(inverted).forEach(([word, positions]) => {
      positions.forEach((position) => { words[position] = word; });
    });
    const abstract = words.filter(Boolean).join(" ");
    return abstract.length > 520 ? `${abstract.slice(0, 520)}…` : abstract;
  };

  const paperUrl = (paper) => (
    paper.doi || paper.primary_location?.landing_page_url || paper.id
  );

  const renderPaper = (paper, index) => {
    const card = document.createElement("article");
    card.className = "paper-card live-paper-card";

    const meta = text("div", "", "meta");
    const venue = paper.primary_location?.source?.display_name || paper.type || "OpenAlex";
    meta.append(text("span", venue));
    meta.append(text("b", String(index + 1)));
    card.append(meta);

    const heading = document.createElement("h2");
    const link = document.createElement("a");
    link.href = paperUrl(paper);
    link.target = "_blank";
    link.rel = "noreferrer";
    link.textContent = paper.display_name || "未命名论文";
    heading.append(link);
    card.append(heading);

    const authors = (paper.authorships || [])
      .slice(0, 6)
      .map((item) => item.author?.display_name)
      .filter(Boolean)
      .join(", ");
    card.append(text("p", authors || "作者信息缺失", "authors"));
    card.append(text("p", reconstructAbstract(paper.abstract_inverted_index), "summary"));

    const footer = document.createElement("footer");
    footer.append(text("span", paper.publication_date || "日期未知"));
    footer.append(text("span", `引用 ${paper.cited_by_count || 0}`));
    if (paper.open_access?.is_oa) footer.append(text("span", "开放获取"));
    const pdfUrl = paper.best_oa_location?.pdf_url || paper.primary_location?.pdf_url;
    if (pdfUrl) {
      const pdf = document.createElement("a");
      pdf.href = pdfUrl;
      pdf.target = "_blank";
      pdf.rel = "noreferrer";
      pdf.textContent = "PDF ↗";
      footer.append(pdf);
    }
    card.append(footer);
    return card;
  };

  const escapeBibtex = (value) => String(value || "")
    .replaceAll("{", "\\{")
    .replaceAll("}", "\\}");

  const makeBibtex = (papers) => papers.map((paper, index) => {
    const authors = (paper.authorships || [])
      .map((item) => item.author?.display_name)
      .filter(Boolean);
    const firstAuthor = (authors[0] || "paper").split(/\s+/).at(-1);
    const year = (paper.publication_date || "nd").slice(0, 4);
    const key = `${firstAuthor}${year}${index + 1}`.replace(/[^A-Za-z0-9]/g, "") || `paper${index + 1}`;
    const fields = [
      ["title", paper.display_name],
      ["author", authors.join(" and ")],
      ["year", year === "nd" ? "" : year],
      ["journal", paper.primary_location?.source?.display_name],
      ["doi", (paper.doi || "").replace("https://doi.org/", "")],
      ["url", paperUrl(paper)],
    ].filter(([, value]) => value);
    return `@article{${key},\n${fields.map(([name, value]) => `  ${name} = {${escapeBibtex(value)}}`).join(",\n")}\n}`;
  }).join("\n\n");

  bibtexButton.addEventListener("click", () => {
    const blob = new Blob([`${makeBibtex(currentResults)}\n`], { type: "application/x-bibtex" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = "litwatch-live-search.bib";
    anchor.click();
    URL.revokeObjectURL(url);
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const values = new FormData(form);
    const query = String(values.get("query") || "").trim();
    const days = Math.max(1, Number(values.get("days") || 90));
    const limit = Math.max(1, Number(values.get("limit") || 20));
    if (query.length < 3) return;

    const start = new Date();
    start.setUTCDate(start.getUTCDate() - days);
    const fromDate = start.toISOString().slice(0, 10);
    const params = new URLSearchParams({
      search: query,
      filter: `from_publication_date:${fromDate},is_retracted:false`,
      sort: "relevance_score:desc,publication_date:desc",
      per_page: String(limit),
      select: "id,display_name,publication_date,type,cited_by_count,doi,authorships,primary_location,best_oa_location,open_access,abstract_inverted_index",
    });

    state.textContent = "正在连接 OpenAlex 并筛选近期论文……";
    state.className = "live-search-state loading";
    resultsRoot.replaceChildren();
    actions.hidden = true;
    form.querySelector("button[type='submit']").disabled = true;

    try {
      const response = await fetch(`https://api.openalex.org/works?${params}`);
      if (!response.ok) throw new Error(`OpenAlex 返回 HTTP ${response.status}`);
      const payload = await response.json();
      currentResults = payload.results || [];
      currentResults.forEach((paper, index) => resultsRoot.append(renderPaper(paper, index)));
      const total = Number(payload.meta?.count || currentResults.length).toLocaleString("zh-CN");
      state.textContent = `已找到约 ${total} 条匹配记录，当前显示前 ${currentResults.length} 篇。`;
      state.className = "live-search-state success";
      actions.hidden = currentResults.length === 0;
      if (!currentResults.length) resultsRoot.append(text("p", "没有找到结果，请扩大回溯时间或改用英文关键词。", "empty"));
    } catch (error) {
      currentResults = [];
      state.textContent = `即时检索失败：${error.message}。你仍可浏览下方每周快照，或进入 Codespaces 深度检索。`;
      state.className = "live-search-state error";
    } finally {
      form.querySelector("button[type='submit']").disabled = false;
    }
  });
})();
