const BASE = '';

async function fetchJSON(url) {
    try {
        const res = await fetch(url);
        return await res.json();
    } catch (err) {
        console.error(`Fetch ${url} failed:`, err);
        return [];
    }
}

async function postJSON(url, body) {
    const res = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
    });
    return res.json();
}

export const fetchEmTechs = () => fetchJSON(`${BASE}/api/emtechs`);
export const fetchTrends = (name) => fetchJSON(`${BASE}/api/emtech/${encodeURIComponent(name)}/trends`);
export const fetchBets = (name) => fetchJSON(`${BASE}/api/emtech/${encodeURIComponent(name)}/bets`);
export const fetchIdeas = (name) => fetchJSON(`${BASE}/api/emtech/${encodeURIComponent(name)}/ideas`);
export const fetchMilestones = (name) => fetchJSON(`${BASE}/api/emtech/${encodeURIComponent(name)}/milestones`);
export const fetchAdvancement = (name) => fetchJSON(`${BASE}/api/emtech/${encodeURIComponent(name)}/advancement`);
export const fetchConvergences = (name) => fetchJSON(`${BASE}/api/emtech/${encodeURIComponent(name)}/convergences`);
export const fetchMilestoneDetail = (name) => fetchJSON(`${BASE}/api/milestone/${encodeURIComponent(name)}`);
export const fetchIdeaDetail = (name) => fetchJSON(`${BASE}/api/idea/${encodeURIComponent(name)}`);

export const postNews = (body) => postJSON(`${BASE}/api/news`, body);
export const postAnalyze = (body) => postJSON(`${BASE}/api/analyze`, body);
export const postTrendAnalyze = (body) => postJSON(`${BASE}/api/trend/analyze`, body);
export const postTrendSpot = (body) => postJSON(`${BASE}/api/trend/spot`, body);
export const postTrendSave = (body) => postJSON(`${BASE}/api/trend/save`, body);
export const postBetEval = (body) => postJSON(`${BASE}/api/bet/evaluate`, body);
export const postIdeaCheck = (body) => postJSON(`${BASE}/api/idea/check`, body);
export const postMap = (body) => postJSON(`${BASE}/api/map`, body);
export const postAdvFilter = (body) => postJSON(`${BASE}/api/advancement/filter`, body);
export const postPathway = (body) => postJSON(`${BASE}/api/advancement/pathway`, body);
