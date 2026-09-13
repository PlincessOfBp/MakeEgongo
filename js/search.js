(function () {
  var input = document.getElementById("search-input");
  var results = document.getElementById("search-results");
  var countEl = document.getElementById("search-count");
  if (!input || !results) return;

  var MAX = 80;

  function params() {
    var p = {};
    location.search.replace(/[?&]([^=]+)=([^&]*)/g, function (_, a, b) {
      p[a] = decodeURIComponent(b.replace(/\+/g, " "));
    });
    return p;
  }

  function esc(s) {
    return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  function mark(text, q) {
    var ql = q.toLowerCase();
    var out = esc(String(text || ""));
    var lower = out.toLowerCase();
    var idx = lower.indexOf(ql);
    if (idx === -1) return out;
    var s = idx > 25 ? "…" + out.slice(idx - 25) : out;
    var ll = s.toLowerCase();
    var start = ll.indexOf(ql);
    if (start === -1) return s;
    return s.slice(0, start) + "<mark>" + s.substr(start, q.length) + "</mark>" + s.slice(start + q.length);
  }

  function run(q) {
    q = (q || "").trim();
    if (!q) {
      results.innerHTML = '<p class="search-empty">검색어를 입력하세요.</p>';
      countEl.textContent = "";
      return;
    }
    var ql = q.toLowerCase();
    var hits = [];
    (window.SEARCH_INDEX || []).forEach(function (item) {
      var text = (item.text || "").toLowerCase();
      var score = -1;
      if ((item.ti || "").toLowerCase().indexOf(ql) === 0) score = 3;
      else if ((item.ti || "").toLowerCase().indexOf(ql) !== -1) score = 2;
      else if (text.indexOf(ql) !== -1) score = 1;
      if (score > 0) hits.push({ item: item, score: score });
    });
    hits.sort(function (a, b) { return b.score - a.score; });
    hits = hits.slice(0, MAX);

    countEl.textContent = hits.length ? hits.length + "건의 결과" : "결과가 없습니다.";
    if (!hits.length) {
      results.innerHTML = '<p class="search-empty">"<b>' + esc(q) + "</b>" + '"에 대한 결과가 없습니다.</p>';
      return;
    }

    var byType = {};
    hits.forEach(function (h) {
      var t = h.item.t || "기타";
      (byType[t] = byType[t] || []).push(h.item);
    });
    var order = ["캐릭터", "세계관 설정", "스토리", "창작물", "관계", "설정 변경 기록", "기타"];
    var html = "";
    order.forEach(function (t) {
      if (!byType[t]) return;
      html += '<div class="search-group-title">' + t + "</div>";
      byType[t].forEach(function (it) {
        html +=
          '<div class="search-item"><a href="' + it.u + '">' +
          '<span class="badge badge-set" style="font-size:10.5px">' + esc(t) + "</span>" +
          "<h3>" + mark(it.ti, q) + "</h3>" +
          (it.s ? "<p>" + mark(it.s, q) + "</p>" : "") +
          "</a></div>";
      });
    });
    results.innerHTML = html;
  }

  var doSearch = function () { run(input.value); };

  var q = params().q;
  if (q) {
    input.value = q;
    run(q);
  }

  input.addEventListener("input", doSearch);
  input.addEventListener("keydown", function (e) {
    if (e.key === "Enter") {
      e.preventDefault();
      var url = location.pathname + "?q=" + encodeURIComponent(input.value);
      history.replaceState(null, "", url);
      run(input.value);
    }
  });

  var clearBtn = document.getElementById("search-clear");
  if (clearBtn) {
    clearBtn.addEventListener("click", function () {
      input.value = "";
      input.focus();
      run("");
    });
  }
})();