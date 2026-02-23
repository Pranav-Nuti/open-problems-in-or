// Mock open problems data - in production this could be loaded from JSON
const PROBLEMS_DATA = [
  {
    id: 1,
    name: "Polynomial-Time Algorithm for Stochastic Queueing Networks",
    author: "J. Michael Harrison",
    difficulty: "Hard",
    chanceOpen: "High",
    slug: "stochastic-queueing-networks"
  },
  {
    id: 2,
    name: "Tight Bounds for Online Bipartite Matching",
    author: "Vahab Mirrokni, Rad Niazadeh",
    difficulty: "Medium",
    chanceOpen: "Medium",
    slug: "online-bipartite-matching"
  },
  {
    id: 3,
    name: "Computational Complexity of Multi-Stage Stochastic Programming",
    author: "Andy Philpott, Alexander Shapiro",
    difficulty: "Hard",
    chanceOpen: "High",
    slug: "multi-stage-stochastic-programming"
  },
  {
    id: 4,
    name: "Approximation Algorithms for the Traveling Salesman Problem with Time Windows",
    author: "David Williamson",
    difficulty: "Medium",
    chanceOpen: "Low",
    slug: "tsp-with-time-windows"
  },
  {
    id: 5,
    name: "Convex Relaxation Tightness for Mixed-Integer Programming",
    author: "Sanjeeb Dash, Oktay Günlük",
    difficulty: "Hard",
    chanceOpen: "High",
    slug: "mip-convex-relaxation"
  },
  {
    id: 6,
    name: "Sample Complexity of Reinforcement Learning in Continuous Action Spaces",
    author: "John Schulman, Pieter Abbeel",
    difficulty: "Hard",
    chanceOpen: "Medium",
    slug: "rl-continuous-actions"
  }
];

const PROBLEMS_PER_PAGE = 3;
