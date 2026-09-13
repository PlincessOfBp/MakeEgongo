(function () {
  var dataEl = document.getElementById("relmap-data");
  if (!dataEl) return;
  var data = JSON.parse(dataEl.textContent);

  var TYPE_COLORS = {
    "친구": "#9cc29a",
    "가족": "#e8b86b",
    "동료": "#7fb3d9",
    "연인": "#d98f8f",
    "라이벌": "#d98f8f",
    "적대": "#c06d6d",
    "협력": "#9cc29a",
    "신뢰": "#7fb3d9",
    "의심": "#c99a5a",
    "존경": "#b79a7f",
    "의존": "#a9a4d4",
    "경쟁": "#c99a5a",
    "자문": "#7fb3d9",
    "거래": "#b79a7f"
  };

  function typeColor(t) {
    if (TYPE_COLORS[t]) return TYPE_COLORS[t];
    var hash = 0;
    for (var i = 0; i < t.length; i++) hash = (hash * 31 + t.charCodeAt(i)) % 360;
    return "hsl(" + hash + ", 45%, 64%)";
  }

  var nodes = data.characters.map(function (c) {
    return {
      id: c.id, name: c.name, kind: c.importance, fav: !!c.is_favorite,
      x: 0, y: 0, vx: 0, vy: 0
    };
  });
  var nodeIdx = {};
  nodes.forEach(function (n, i) { nodeIdx[n.id] = i; });

  var links = data.relationships.map(function (r) {
    return {
      id: r.id, type: r.type || "기타", desc: r.description || "", status: r.status || "",
      si: nodeIdx[r.source], ti: nodeIdx[r.target]
    };
  }).filter(function (l) { return l.si !== undefined && l.ti !== undefined; });

  var box = document.getElementById("relmap");
  var W = box.clientWidth, H = box.clientHeight;

  var types = [];
  links.forEach(function (l) {
    if (types.indexOf(l.type) === -1) types.push(l.type);
  });
  var legend = document.getElementById("relmap-legend");
  if (legend) {
    legend.innerHTML = types.map(function (t) {
      return '<span class="lg-type"><span style="display:inline-block;width:34px;height:3px;background:' + typeColor(t) + ';border-radius:2px;vertical-align:middle;margin-right:6px"></span>' + t + "</span>";
    }).join("");
  }

  var k = Math.sqrt((W * H) / Math.max(nodes.length, 1)) * 1.1;
  var CENTER_X = W / 2, CENTER_Y = H / 2;

  function iterate(cooling) {
    var i, j, dx, dy, d2, d, f;
    for (i = 0; i < nodes.length; i++) {
      var n = nodes[i];
      n.vx = 0; n.vy = 0;
      for (j = 0; j < nodes.length; j++) {
        if (i === j) continue;
        var m = nodes[j];
        dx = n.x - m.x; dy = n.y - m.y;
        d2 = dx * dx + dy * dy || 0.01;
        d = Math.sqrt(d2);
        f = Math.min(k * k / d2, 120);
        n.vx += (dx / d) * f;
        n.vy += (dy / d) * f;
      }
      n.vx += (CENTER_X - n.x) * 0.02;
      n.vy += (CENTER_Y - n.y) * 0.02;
    }
    for (i = 0; i < nodes.length; i++) {
      var a = nodes[i];
      for (j = i + 1; j < nodes.length; j++) {
        var b = nodes[j];
        dx = b.x - a.x; dy = b.y - a.y;
        d = Math.sqrt(dx * dx + dy * dy) || 0.1;
        f = (d - k * 1.25) / d * 0.12;
        a.vx += dx * f; a.vy += dy * f;
        b.vx -= dx * f; b.vy -= dy * f;
      }
    }
    for (i = 0; i < nodes.length; i++) {
      var nd = nodes[i];
      nd.x += nd.vx * cooling;
      nd.y += nd.vy * cooling;
      nd.x = Math.max(24, Math.min(W - 24, nd.x));
      nd.y = Math.max(30, Math.min(H - 30, nd.y));
    }
  }

  var seed = 12345;
  function rnd() { seed = (seed * 16807) % 2147483647; return (seed - 1) / 2147483646; }
  nodes.forEach(function (n, i) {
    var ang = (i / Math.max(nodes.length, 1)) * Math.PI * 2;
    n.x = CENTER_X + Math.cos(ang) * (Math.min(W, H) / 4) * (0.5 + rnd());
    n.y = CENTER_Y + Math.sin(ang) * (Math.min(W, H) / 4) * (0.5 + rnd());
  });

  for (var iter = 0; iter < 320; iter++) iterate(1 - iter / 320);

  function addLabels(d) {
    return d.replace(/[^0-9a-zA-Z가-힣 ._-]/g, "");
  }

  var svgNS = "http://www.w3.org/2000/svg";
  var svg = document.createElementNS(svgNS, "svg");
  var view = document.createElementNS(svgNS, "g");
  svg.appendChild(view);
  box.appendChild(svg);

  var scale = 1, tx = 0, ty = 0;
  var dragging = false, dragMoved = false, sx = 0, sy = 0;

  var linkEls = [], nodeEls = [];
  var hoverNode = null;

  function draw() {
    while (view.firstChild) view.removeChild(view.firstChild);
    linkEls = []; nodeEls = [];

    links.forEach(function (l) {
      var a = nodes[l.si], b = nodes[l.ti];
      var midX = (a.x + b.x) / 2, midY = (a.y + b.y) / 2;
      var path = document.createElementNS(svgNS, "path");
      var dx = b.x - a.x, dy = b.y - a.y;
      var bend = Math.max(14, Math.min(40, Math.hypot(dx, dy) * 0.25));
      var px = -dy, py = dx, pl = Math.hypot(px, py) || 1;
      var c1x = a.x + dx / 3 + (px / pl) * bend, c1y = a.y + dy / 3 + (py / pl) * bend;
      var c2x = a.x + dx * 2 / 3 + (px / pl) * bend, c2y = a.y + dy * 2 / 3 + (py / pl) * bend;
      path.setAttribute("d", "M" + a.x + "," + a.y + " C" + c1x + "," + c1y + " " + c2x + "," + c2y + " " + b.x + "," + b.y);
      path.setAttribute("fill", "none");
      path.setAttribute("stroke", typeColor(l.type));
      path.setAttribute("stroke-width", "1.6");
      path.setAttribute("opacity", "0.75");
      path.classList.add("rel-edge");
      view.appendChild(path);

      var hit = document.createElementNS(svgNS, "line");
      hit.setAttribute("x1", a.x); hit.setAttribute("y1", a.y);
      hit.setAttribute("x2", b.x); hit.setAttribute("y2", b.y);
      hit.setAttribute("stroke", "transparent");
      hit.setAttribute("stroke-width", "18");
      hit.style.cursor = "pointer";
      hit.addEventListener("click", function (event) {
        event.stopPropagation();
        var target = document.getElementById(l.id);
        if (target) {
          target.scrollIntoView({ behavior: "smooth", block: "center" });
          target.style.transition = "box-shadow 0.4s";
          target.style.boxShadow = "0 0 0 3px " + typeColor(l.type);
          setTimeout(function () { target.style.boxShadow = ""; }, 1200);
        } else {
          location.hash = "#" + l.id;
        }
      });
      view.appendChild(hit);

      var tip = document.createElementNS(svgNS, "title");
      tip.textContent = l.type + " — " + addLabels(l.desc).slice(0, 80);
      path.appendChild(tip);
      linkEls.push({ el: path, l: l });
    });

    nodes.forEach(function (n) {
      var gEl = document.createElementNS(svgNS, "g");
      var r = n.kind === "major" ? 9 : 7;
      var circle = document.createElementNS(svgNS, "circle");
      circle.setAttribute("cx", n.x);
      circle.setAttribute("cy", n.y);
      circle.setAttribute("r", r);
      circle.setAttribute("fill", n.fav ? "#d98f8f" : "#1f2935");
      circle.setAttribute("stroke", n.fav ? "#e7b9b9" : "#e8b86b");
      circle.setAttribute("stroke-width", n.fav ? 3 : 2);
      circle.style.cursor = "pointer";
      gEl.appendChild(circle);

      var text = document.createElementNS(svgNS, "text");
      text.setAttribute("x", n.x);
      text.setAttribute("y", n.y + r + 16);
      text.setAttribute("text-anchor", "middle");
      text.setAttribute("fill", "#93a4b5");
      text.setAttribute("font-size", "12.5px");
      text.textContent = n.name;
      text.style.cursor = "pointer";
      gEl.appendChild(text);

      gEl.addEventListener("click", function (event) {
        event.stopPropagation();
        window.location.href = "../characters/" + encodeURIComponent(n.id) + ".html";
      });
      gEl.addEventListener("mouseenter", function () {
        hoverNode = n.id;
        linkEls.forEach(function (le) {
          le.el.setAttribute("opacity", (le.l.si === nodeIdx[n.id] || le.l.ti === nodeIdx[n.id]) ? "1" : "0.15");
          le.el.setAttribute("stroke-width", (le.l.si === nodeIdx[n.id] || le.l.ti === nodeIdx[n.id]) ? "2.6" : "1.2");
        });
        nodes.forEach(function (nn) {
          var other = nn.id === n.id;
          var el = nodeEls[nodeIdx[nn.id]];
          if (!el) return;
          el.querySelector("circle").setAttribute("opacity", other ? "1" : "0.35");
          el.querySelector("text").setAttribute("opacity", other ? "1" : "0.35");
        });
      });
      view.appendChild(gEl);
      nodeEls.push(gEl);
    });

    svg.setAttribute("viewBox", "0 0 " + W + " " + H);
  }

  function resetView() {
    scale = 1; tx = 0; ty = 0;
    view.setAttribute("transform", "translate(0,0) scale(1)");
  }

  svg.addEventListener("mousedown", function (e) {
    dragging = true; dragMoved = false; sx = e.offsetX; sy = e.offsetY;
  });
  svg.addEventListener("mousemove", function (e) {
    if (!dragging) return;
    var dx = e.offsetX - sx, dy = e.offsetY - sy;
    if (Math.abs(dx) + Math.abs(dy) > 3) dragMoved = true;
    tx += dx; ty += dy; sx = e.offsetX; sy = e.offsetY;
    view.setAttribute("transform", "translate(" + tx + "," + ty + ") scale(" + scale + ")");
  });
  window.addEventListener("mouseup", function () { dragging = false; });

  svg.addEventListener("wheel", function (e) {
    e.preventDefault();
    e.stopPropagation();
    var delta = e.deltaY > 0 ? 0.9 : 1.12;
    scale = Math.max(0.4, Math.min(3, scale * delta));
    view.setAttribute("transform", "translate(" + tx + "," + ty + ") scale(" + scale + ")");
  }, { passive: false });

  svg.addEventListener("click", function () { resetView(); });
  window.addEventListener("resize", function () {
    W = box.clientWidth; H = box.clientHeight;
    draw();
  });

  draw();
})();