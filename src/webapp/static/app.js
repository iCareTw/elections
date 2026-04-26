const state = {
  elections: [],
  selectedElection: null,
  reviewItems: [],
  currentIndex: 0,
  selectedCandidateId: null,
  expandedNodes: new Set(),
};

const STATUS_LABELS = {
  todo: "未匯入",
  review: "待審核",
  done: "已完成",
};

const els = {
  electionList: document.querySelector("#election-list"),
  refresh: document.querySelector("#refresh-elections"),
  loadElection: document.querySelector("#load-election"),
  buildOutput: document.querySelector("#build-output"),
  pathline: document.querySelector("#pathline"),
  title: document.querySelector("#workspace-title"),
  status: document.querySelector("#status"),
  incoming: document.querySelector("#incoming-record"),
  matchList: document.querySelector("#match-list"),
  useMatch: document.querySelector("#use-match"),
  createNew: document.querySelector("#create-new"),
  skipRecord: document.querySelector("#skip-record"),
};

function setStatus(message, kind = "info") {
  els.status.textContent = message;
  els.status.dataset.kind = kind;
}

async function request(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await response.json();
  if (!response.ok || data.error) {
    throw new Error(data.error || `Request failed: ${response.status}`);
  }
  return data;
}

function normalizePath(value) {
  return String(value || "").replaceAll("\\", "/");
}

function treeSegments(election) {
  const parts = normalizePath(election.path).split("/").filter(Boolean);
  const dataIndex = parts.indexOf("_data");
  if (dataIndex >= 0) {
    return parts.slice(dataIndex + 1);
  }
  return [];
}

function buildElectionTree(elections) {
  const roots = [];
  const nodeIndex = new Map();
  const defaultExpanded = new Set();

  for (const election of elections) {
    const segments = treeSegments(election);
    if (segments.length === 0) {
      continue;
    }
    let children = roots;
    let path = "";

    segments.forEach((segment, index) => {
      path = path ? `${path}/${segment}` : segment;
      let node = nodeIndex.get(path);
      const isLeaf = index === segments.length - 1;
      if (!node) {
        node = {
          key: path,
          label: segment,
          depth: index,
          kind: isLeaf ? "file" : "dir",
          election: null,
          children: [],
        };
        nodeIndex.set(path, node);
        children.push(node);
        if (!isLeaf) {
          if (index <= 2) {
            defaultExpanded.add(path);
          }
        }
      }

      if (isLeaf) {
        node.kind = "file";
        node.election = election;
      } else {
        node.kind = "dir";
      }

      children = node.children;
    });
  }

  const collator = new Intl.Collator("zh-Hant", { numeric: true, sensitivity: "base" });
  const sortNodes = (nodes) => {
    nodes.sort((left, right) => {
      if (left.kind !== right.kind) {
        return left.kind === "dir" ? -1 : 1;
      }
      return collator.compare(left.label, right.label);
    });
    nodes.forEach((node) => sortNodes(node.children));
  };
  sortNodes(roots);
  if (state.expandedNodes.size === 0) {
    state.expandedNodes = defaultExpanded;
  }
  return roots;
}

function electionMeta(election) {
  const statusLabel = STATUS_LABELS[election.status] || election.status;
  if (election.unresolved_count > 0) {
    return `${election.unresolved_count}待審`;
  }
  if (election.imported_count > 0) {
    return "完成";
  }
  return statusLabel;
}

function expandElectionParents(election) {
  const segments = treeSegments(election);
  let path = "";
  for (const segment of segments.slice(0, -1)) {
    path = path ? `${path}/${segment}` : segment;
    state.expandedNodes.add(path);
  }
}

function renderTreeNodes(nodes, container) {
  for (const node of nodes) {
    const wrapper = document.createElement("div");
    wrapper.className = `tree-node ${node.kind}`;
    wrapper.style.setProperty("--depth", node.depth);

    if (node.kind === "dir") {
      const expanded = state.expandedNodes.has(node.key);
      const row = document.createElement("button");
      row.type = "button";
      row.className = "tree-row tree-dir";
      row.setAttribute("aria-expanded", String(expanded));
      row.innerHTML = `
        <span class="tree-toggle">${expanded ? "▾" : "▸"}</span>
        <span class="tree-label">${node.label}</span>
      `;
      row.addEventListener("click", () => {
        if (state.expandedNodes.has(node.key)) {
          state.expandedNodes.delete(node.key);
        } else {
          state.expandedNodes.add(node.key);
        }
        renderElections();
      });
      wrapper.append(row);

      if (expanded) {
        const children = document.createElement("div");
        children.className = "tree-children";
        renderTreeNodes(node.children, children);
        wrapper.append(children);
      }
    } else {
      const election = node.election;
      const row = document.createElement("button");
      row.type = "button";
      row.className = "tree-row tree-file";
      if (state.selectedElection?.election_id === election.election_id) {
        row.classList.add("selected");
      }
      row.innerHTML = `
        <span class="tree-label">${node.label}</span>
        <span class="tree-meta">${electionMeta(election)}</span>
      `;
      row.title = election.election_id;
      row.addEventListener("click", () => selectElection(election));
      wrapper.append(row);
    }

    container.append(wrapper);
  }
}

function renderElections() {
  els.electionList.innerHTML = "";
  const tree = buildElectionTree(state.elections);
  renderTreeNodes(tree, els.electionList);
}

function selectElection(election) {
  expandElectionParents(election);
  state.selectedElection = election;
  state.reviewItems = [];
  state.currentIndex = 0;
  state.selectedCandidateId = null;
  els.loadElection.disabled = false;
  els.pathline.textContent = election.election_id;
  els.title.textContent = election.label;
  renderElections();
  renderCurrentItem();
}

function field(label, value) {
  return `<div><span>${label}</span><strong>${value ?? "未知"}</strong></div>`;
}

function renderRecord(record) {
  return `
    ${field("姓名", record.name)}
    ${field("生日", record.birthday)}
    ${field("年份", record.year)}
    ${field("選別", record.type)}
    ${field("區域", record.region)}
    ${field("政黨", record.party)}
  `;
}

function renderCurrentItem() {
  state.selectedCandidateId = null;
  const item = state.reviewItems[state.currentIndex];
  const hasItem = Boolean(item);

  els.useMatch.disabled = true;
  els.createNew.disabled = !hasItem;
  els.skipRecord.disabled = !hasItem;
  els.matchList.innerHTML = "";

  if (!hasItem) {
    els.incoming.className = "record-card empty";
    els.incoming.textContent = state.selectedElection ? "目前沒有待人工審核項目。" : "尚未載入待審核資料。";
    return;
  }

  els.incoming.className = "record-card";
  els.incoming.innerHTML = renderRecord(item.record);

  item.matches.forEach((candidate) => {
    const button = document.createElement("button");
    button.className = "match-card";
    button.innerHTML = `
      <strong>${candidate.name}</strong>
      <span>${candidate.id}</span>
      <em>birthday: ${candidate.birthday ?? "未知"}</em>
    `;
    button.addEventListener("click", () => {
      state.selectedCandidateId = candidate.id;
      document.querySelectorAll(".match-card").forEach((node) => node.classList.remove("selected"));
      button.classList.add("selected");
      els.useMatch.disabled = false;
    });
    els.matchList.append(button);
  });
}

async function loadElections() {
  const selectedElectionId = state.selectedElection?.election_id;
  setStatus("Loading elections...");
  state.elections = await request("/api/elections");
  state.selectedElection =
    state.elections.find((election) => election.election_id === selectedElectionId && treeSegments(election).length > 0) || null;
  renderElections();
  setStatus(`Loaded ${state.elections.filter((election) => treeSegments(election).length > 0).length} elections.`);
}

async function loadSelectedElection() {
  if (!state.selectedElection) return;
  setStatus("Importing source records and classifying candidates...");
  const summary = await request("/api/elections/load", {
    method: "POST",
    body: JSON.stringify({ election_id: state.selectedElection.election_id }),
  });
  state.elections = await request("/api/elections");
  state.selectedElection =
    state.elections.find(
      (election) => election.election_id === state.selectedElection.election_id && treeSegments(election).length > 0,
    ) || state.selectedElection;
  renderElections();
  state.reviewItems = await request(`/api/review-items?election_id=${encodeURIComponent(state.selectedElection.election_id)}`);
  state.currentIndex = 0;
  renderCurrentItem();
  setStatus(`Imported ${summary.imported}; auto/new ${summary.auto}; manual ${summary.manual}.`);
}

async function saveResolution(mode, candidateId = null) {
  const item = state.reviewItems[state.currentIndex];
  if (!item) return;

  await request("/api/resolutions", {
    method: "POST",
    body: JSON.stringify({
      election_id: item.election_id,
      source_record_id: item.source_record_id,
      candidate_id: candidateId,
      mode,
    }),
  });

  state.reviewItems.splice(state.currentIndex, 1);
  state.elections = await request("/api/elections");
  state.selectedElection =
    state.elections.find((election) => election.election_id === item.election_id && treeSegments(election).length > 0) || null;
  renderElections();
  renderCurrentItem();
  setStatus(`Saved ${mode} decision. ${state.reviewItems.length} manual items remain.`);
}

els.refresh.addEventListener("click", () => loadElections().catch((error) => setStatus(error.message, "error")));
els.loadElection.addEventListener("click", () => loadSelectedElection().catch((error) => setStatus(error.message, "error")));
els.useMatch.addEventListener("click", () => saveResolution("manual", state.selectedCandidateId).catch((error) => setStatus(error.message, "error")));
els.createNew.addEventListener("click", () => saveResolution("new").catch((error) => setStatus(error.message, "error")));
els.skipRecord.addEventListener("click", () => saveResolution("skip").catch((error) => setStatus(error.message, "error")));
els.buildOutput.addEventListener("click", async () => {
  try {
    const result = await request("/api/build", { method: "POST", body: "{}" });
    state.elections = await request("/api/elections");
    renderElections();
    setStatus(result.error || `Build complete. Wrote ${result.count} candidates.`);
  } catch (error) {
    setStatus(error.message, "error");
  }
});

loadElections().catch((error) => setStatus(error.message, "error"));
