// Mock open problems data - in production this could be loaded from JSON
const PROBLEMS_DATA = [
  { id: 1, name: "Polynomial-Time Algorithm for Stochastic Queueing Networks", author: "J. Michael Harrison" },
  { id: 2, name: "Tight Bounds for Online Bipartite Matching", author: "Vahab Mirrokni, Rad Niazadeh" },
  { id: 3, name: "Computational Complexity of Multi-Stage Stochastic Programming", author: "Andy Philpott, Alexander Shapiro" },
  { id: 4, name: "Approximation Algorithms for the Traveling Salesman Problem with Time Windows", author: "David Williamson" },
  { id: 5, name: "Convex Relaxation Tightness for Mixed-Integer Programming", author: "Sanjeeb Dash, Oktay Günlük" },
  { id: 6, name: "Sample Complexity of Reinforcement Learning in Continuous Action Spaces", author: "John Schulman, Pieter Abbeel" }
];

const PROBLEMS_PER_PAGE = 3;
