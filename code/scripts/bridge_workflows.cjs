const s = require("/usr/local/lib/node_modules/n8n/node_modules/sqlite3");
const db = new s.Database("/home/node/.n8n/database.sqlite");

const v4 = () => {
  let h = "xxxxxxxxxxxx".replace(/x/g,()=>((Math.random()*16)|0).toString(16));
  return `${h.slice(0,8)}-${h.slice(8,12)}-4${h.slice(12,15)}-${((Math.random()*4|8).toString(16))}${h.slice(15,18)}-${h.slice(18,23)}${h.slice(23,25)}${((Math.random()*16)|0).toString(16)}${((Math.random()*16)|0).toString(16)}`;
};

const PROJECT_ID = "3RMihEqTonI08xPx";

const workflows = {
  "system-health": {
    name: "System Health",
    nodes: [
      { id: "a1", name: "Webhook", type: "n8n-nodes-base.webhook", typeVersion: 1, position: [250,300],
        parameters: { httpMethod: "POST", path: "system-health", responseMode: "lastNode", responseData: "all", options: {} },
        webhookId: "wh-syshealth" },
      { id: "b2", name: "Fetch Health", type: "n8n-nodes-base.httpRequest", typeVersion: 4.2, position: [500,300],
        parameters: { url: "http://172.18.0.1:9199/system-health", method: "GET", authentication: "none", sendQuery: false, sendBody: false, sendHeaders: false, options: {} } },
      { id: "c3", name: "Respond", type: "n8n-nodes-base.respondToWebhook", typeVersion: 1, position: [750,300],
        parameters: { respondWith: "json", value: "={{ $json }}" } },
    ],
    connections: {
      "Webhook": { main: [[{ node: "Fetch Health", type: "main", index: 0 }]] },
      "Fetch Health": { main: [[{ node: "Respond", type: "main", index: 0 }]] },
    },
  },
  "docker-list": {
    name: "Docker List",
    nodes: [
      { id: "d1", name: "Webhook", type: "n8n-nodes-base.webhook", typeVersion: 1, position: [250,300],
        parameters: { httpMethod: "POST", path: "docker-list", responseMode: "lastNode", responseData: "all", options: {} },
        webhookId: "wh-dkrlist" },
      { id: "e2", name: "Fetch Docker", type: "n8n-nodes-base.httpRequest", typeVersion: 4.2, position: [500,300],
        parameters: { url: "http://172.18.0.1:9199/docker-ps", method: "GET", authentication: "none", sendQuery: false, sendBody: false, sendHeaders: false, options: {} } },
      { id: "f3", name: "Respond", type: "n8n-nodes-base.respondToWebhook", typeVersion: 1, position: [750,300],
        parameters: { respondWith: "json", value: "={{ $json }}" } },
    ],
    connections: {
      "Webhook": { main: [[{ node: "Fetch Docker", type: "main", index: 0 }]] },
      "Fetch Docker": { main: [[{ node: "Respond", type: "main", index: 0 }]] },
    },
  },
  "health-digest": {
    name: "Health Digest",
    nodes: [
      { id: "g1", name: "Webhook", type: "n8n-nodes-base.webhook", typeVersion: 1, position: [250,300],
        parameters: { httpMethod: "POST", path: "health-digest", responseMode: "lastNode", responseData: "all", options: {} },
        webhookId: "wh-hlthdgst" },
      { id: "h2", name: "Fetch Health", type: "n8n-nodes-base.httpRequest", typeVersion: 4.2, position: [500,300],
        parameters: { url: "http://172.18.0.1:9199/system-health", method: "GET", authentication: "none", sendQuery: false, sendBody: false, sendHeaders: false, options: {} } },
      { id: "i3", name: "Format", type: "n8n-nodes-base.code", typeVersion: 1, position: [750,300],
        parameters: { mode: "runOnceForAllItems", jsCode: "const s = $json.services || {};\nconst lines = Object.entries(s).map(([k,v]) => k+\": \"+v);\nreturn {digest: lines.join(\"\\n\") || \"All services running\", ts: new Date().toISOString()};" } },
      { id: "j4", name: "Respond", type: "n8n-nodes-base.respondToWebhook", typeVersion: 1, position: [1000,300],
        parameters: { respondWith: "json", value: "={{ $json }}" } },
    ],
    connections: {
      "Webhook": { main: [[{ node: "Fetch Health", type: "main", index: 0 }]] },
      "Fetch Health": { main: [[{ node: "Format", type: "main", index: 0 }]] },
      "Format": { main: [[{ node: "Respond", type: "main", index: 0 }]] },
    },
  },
};

let pending = Object.keys(workflows).length;
let ok = 0, fail = 0;

for (const [key, wf] of Object.entries(workflows)) {
  const wid = v4(), vid = v4(), wuid = wf.nodes[0].webhookId;
  const nodesJson = JSON.stringify(wf.nodes);
  const connJson = JSON.stringify(wf.connections);

  db.run(
    `INSERT INTO workflow_entity (id, name, active, nodes, connections, versionId, activeVersionId, triggerCount, createdAt, updatedAt, settings, pinData, versionCounter, description, nodeGroups, sourceWorkflowId, isArchived)
     VALUES (?, ?, 1, ?, ?, ?, ?, 0, STRFTIME('%%Y-%%m-%%d %%H:%%M:%%f', 'NOW'), STRFTIME('%%Y-%%m-%%d %%H:%%M:%%f', 'NOW'), '{}', '{}', 1, '', '[]', NULL, 0)`,
    [wid, wf.name, nodesJson, connJson, vid, vid],
    (err) => {
      if (err) { console.log(key+": FAIL insert -> "+err.message); fail++; }
      else {
        db.run(
          `INSERT OR FAIL INTO shared_workflow (workflowId, projectId, role)
           VALUES (?, ?, 'workflow:owner')`,
          [wid, PROJECT_ID],
          () => {}  // ignore shared_workflow errors
        );
        db.run(
          `INSERT OR FAIL INTO webhook_entity (workflowId, webhookPath, method, node, webhookId, pathLength)
           VALUES (?, ?, "POST", ?, ?, ?)`,
          [wid, wf.nodes[0].parameters.path, nodesJson, wuid, wf.nodes[0].parameters.path.length],
          (err2) => {
            if (err2) { console.log(key+": FAIL webhook -> "+err2.message); fail++; }
            else {
              // Insert published snapshot into workflow_history
              db.run(
                `INSERT OR FAIL INTO workflow_history (versionId, workflowId, authors, nodes, connections, name, autosaved, createdAt, updatedAt, nodeGroups)
                 VALUES (?, ?, 'admin', ?, ?, ?, 0, STRFTIME('%%Y-%%m-%%d %%H:%%M:%%f', 'NOW'), STRFTIME('%%Y-%%m-%%d %%H:%%M:%%f', 'NOW'), '[]')`,
                [vid, wid, nodesJson, connJson, wf.name],
                (err3) => {
                  if (err3) { console.log(key+": FAIL history -> "+err3.message); fail++; }
                  else {
                    db.run(
                      `INSERT OR FAIL INTO workflow_published_version (workflowId, publishedVersionId)
                       VALUES (?, ?)`,
                      [wid, vid],
                      (err4) => {
                        if (err4) { console.log(key+": FAIL pubver -> "+err4.message); fail++; }
                        else { console.log(key+": OK"); ok++; }
                        pending--;
                        if (!pending) {
                          console.log("Done: "+ok+" ok, "+fail+" fail");
                          db.close();
                        }
                      }
                    );
                  }
                }
              );
            }
          }
        );
      }
    }
  );
}
