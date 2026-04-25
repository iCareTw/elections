const state = {
  elections: [],
  selectedElection: null,
  reviewItems: [],
  currentIndex: 0,
  selectedCandidateId: null,
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

function groupByType(elections) {
  return elections.reduce((groups, election) => {
    groups[election.type] ||= [];
    groups[election.type].push(election);
    return groups;
  }, {});
}

function renderElections() {
  const groups = groupByType(state.elections);
  els.electionList.innerHTML = "";

  for (const [type, elections] of Object.entries(groups)) {
    const section = document.createElement("section");
    section.className = "election-group";
    section.innerHTML = `<h3>${type}</h3>`;

    for (const election of elections) {
      const button = document.createElement("button");
      button.className = "election-item";
      if (state.selectedElection?.election_id === election.election_id) {
        button.classList.add("selected");
      }
      button.innerHTML = `
        <span>${election.year || election.session || "?"}</span>
        <strong>${election.label}</strong>
        <em>${election.status}</em>
      `;
      button.addEventListener("click", () => selectElection(election));
      section.append(button);
    }
    els.electionList.append(section);
  }
}

function selectElection(election) {
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
  setStatus("Loading elections...");
  state.elections = await request("/api/elections");
  renderElections();
  setStatus(`Loaded ${state.elections.length} elections.`);
}

async function loadSelectedElection() {
  if (!state.selectedElection) return;
  setStatus("Importing source records and classifying candidates...");
  const summary = await request("/api/elections/load", {
    method: "POST",
    body: JSON.stringify({ election_id: state.selectedElection.election_id }),
  });
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
    setStatus(result.error || "Build complete.");
  } catch (error) {
    setStatus(error.message, "error");
  }
});

loadElections().catch((error) => setStatus(error.message, "error"));
