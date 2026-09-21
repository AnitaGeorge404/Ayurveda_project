(function () {
  "use strict";

  const PRED_LABEL = {
    HAS_ACTION: "has action", TREATS_PATHOLOGY: "treats", AFFECTS_FUNCTION: "affects",
    HAS_REFERENCE: "references", IS_A: "is a",
  };

  const SAMPLE_QUESTIONS = [
    "What pathologies does Brahmi treat?",
    "Which herbs affect Smriti?",
    "What does Giloy treat?",
    "List all herbs",
    "What is the mechanism of Simhadi?",
    "What is the capital of France?",
  ];

  const log = document.getElementById("log");
  const chips = document.getElementById("chips");
  const form = document.getElementById("askform");
  const input = document.getElementById("q");
  const button = document.getElementById("ask");
  const healthDot = document.getElementById("healthDot");
  const healthText = document.getElementById("healthText");

  function renderChips() {
    for (const q of SAMPLE_QUESTIONS) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "chip";
      btn.textContent = q;
      btn.addEventListener("click", () => ask(q));
      chips.appendChild(btn);
    }
  }

  function addUser(text) {
    const row = document.createElement("div");
    row.className = "bubble-row user";
    const bubble = document.createElement("div");
    bubble.className = "bubble user";
    bubble.textContent = text;
    row.appendChild(bubble);
    log.appendChild(row);
    return row;
  }

  function addTyping() {
    const row = document.createElement("div");
    row.className = "bubble-row system";
    row.innerHTML = `<div class="bubble system"><div class="typing"><span></span><span></span><span></span></div></div>`;
    log.appendChild(row);
    return row;
  }

  function renderSystem(row, result) {
    row.innerHTML = "";
    const bubble = document.createElement("div");
    bubble.className = `bubble system status-${result.status}`;

    const pill = document.createElement("div");
    pill.className = `status-pill status-${result.status}`;
    pill.textContent = result.status.replace(/_/g, " ");
    bubble.appendChild(pill);

    const ans = document.createElement("div");
    ans.className = "answer-text";
    ans.textContent = result.answer;
    bubble.appendChild(ans);

    if (result.evidence && result.evidence.length) {
      const det = document.createElement("details");
      det.className = "evidence";
      const sum = document.createElement("summary");
      sum.textContent = `evidence (${result.evidence.length} record${result.evidence.length === 1 ? "" : "s"})`;
      det.appendChild(sum);
      result.evidence.slice(0, 40).forEach((r) => {
        const rowEl = document.createElement("div");
        rowEl.className = "ev-row";
        const src = r.source_file ? `${r.source_file}:${r.source_row}` : "";
        rowEl.innerHTML =
          `<span class="ev-main"></span><span class="ev-pred"></span><span class="ev-main"></span>` +
          (src ? `<span class="ev-src"></span>` : "");
        const spans = rowEl.querySelectorAll(".ev-main, .ev-pred, .ev-src");
        spans[0].textContent = r.subject;
        spans[1].textContent = `[${PRED_LABEL[r.predicate] || r.predicate}]`;
        spans[2].textContent = r.value;
        if (src) spans[3].textContent = src;
        det.appendChild(rowEl);
      });
      const btnVis = document.createElement("button");
      btnVis.className = "btn-visualize";
      btnVis.textContent = "Visualize Graph";
      const graphContainer = document.createElement("div");
      graphContainer.className = "graph-container";
      graphContainer.style.display = "none";
      
      btnVis.addEventListener("click", () => {
        if (graphContainer.style.display === "none") {
          graphContainer.style.display = "block";
          btnVis.textContent = "Hide Graph";
          
          const nodes = new vis.DataSet();
          const edges = new vis.DataSet();
          const nodeSet = new Set();
          
          result.evidence.forEach((r, i) => {
            if (!nodeSet.has(r.subject)) {
              nodes.add({ id: r.subject, label: r.subject });
              nodeSet.add(r.subject);
            }
            if (!nodeSet.has(r.value)) {
              nodes.add({ id: r.value, label: r.value });
              nodeSet.add(r.value);
            }
            edges.add({ from: r.subject, to: r.value, label: PRED_LABEL[r.predicate] || r.predicate, font: {size: 10, align: 'middle'} });
          });
          
          const networkData = { nodes: nodes, edges: edges };
          const options = {
            nodes: { shape: 'box', font: { color: '#ffffff' }, color: { background: '#2c3e50', border: '#34495e' } },
            edges: { color: '#7f8c8d', arrows: 'to' },
            physics: { barnesHut: { gravitationalConstant: -2000, centralGravity: 0.3, springLength: 95 } }
          };
          new vis.Network(graphContainer, networkData, options);
        } else {
          graphContainer.style.display = "none";
          btnVis.textContent = "Visualize Graph";
        }
      });
      
      det.appendChild(btnVis);
      det.appendChild(graphContainer);
      bubble.appendChild(det);
    }

    row.appendChild(bubble);
  }

  async function ask(question) {
    addUser(question);
    const typingRow = addTyping();
    button.disabled = true;
    window.scrollTo({ top: document.body.scrollHeight, behavior: "smooth" });

    try {
      const res = await fetch("/api/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question }),
      });
      if (!res.ok) {
        let msg = `HTTP ${res.status}`;
        try {
          const errData = await res.json();
          if (errData.detail) msg += `: ${errData.detail}`;
        } catch (e) {}
        throw new Error(msg);
      }
      const data = await res.json();
      renderSystem(typingRow, data);
    } catch (err) {
      renderSystem(typingRow, {
        status: "ERROR",
        answer: `Could not reach the backend (${err.message}). Is it deployed and is NEO4J_URI reachable?`,
        evidence: [],
      });
    } finally {
      button.disabled = false;
      window.scrollTo({ top: document.body.scrollHeight, behavior: "smooth" });
    }
  }

  async function checkHealth() {
    try {
      const res = await fetch("/api/health");
      if (!res.ok) throw new Error();
      healthDot.classList.add("ok");
      healthText.textContent = "Backend connected";
    } catch {
      healthDot.classList.add("down");
      healthText.textContent = "Backend unreachable";
    }
  }

  renderChips();
  checkHealth();

  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const question = input.value.trim();
    if (!question) return;
    input.value = "";
    ask(question);
  });

  // Voice Input Logic
  const micButton = document.getElementById("mic");
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  
  if (SpeechRecognition) {
    const recognition = new SpeechRecognition();
    recognition.continuous = false;
    recognition.interimResults = false;
    // Don't set hardcoded lang so it inherits from the browser or OS
    
    recognition.onstart = function() {
      micButton.classList.add("listening");
    };
    
    recognition.onresult = function(event) {
      const transcript = event.results[0][0].transcript;
      input.value = transcript;
      // Auto-submit after transcription
      button.click();
    };
    
    recognition.onerror = function(event) {
      console.error("Speech recognition error", event.error);
      micButton.classList.remove("listening");
    };
    
    recognition.onend = function() {
      micButton.classList.remove("listening");
    };
    
    micButton.addEventListener("click", () => {
      if (micButton.classList.contains("listening")) {
        recognition.stop();
      } else {
        recognition.start();
      }
    });
  } else {
    micButton.style.display = "none";
    console.warn("Speech recognition not supported in this browser.");
  }
})();
