/**
 * One-click starting points.
 *
 * Most visitors arrive with no job description to hand, and asking them to find
 * and paste one before anything happens is where a demo loses people. Each of
 * these fills the form with a realistic posting so the interview can start on
 * the next click.
 */
export interface ExampleRole {
  id: string
  label: string
  role: string
  jobDescription: string
}

export const EXAMPLE_ROLES: ExampleRole[] = [
  {
    id: 'ml-engineer',
    label: 'ML Engineer',
    role: 'Machine Learning Engineer',
    jobDescription:
      'Senior Machine Learning Engineer — personalization and ranking.\n' +
      'You will own ranking models end to end: feature pipelines, training, ' +
      'offline and online evaluation, deployment, and monitoring. ' +
      'Requirements: 5+ years of production ML, strong Python, experience with ' +
      'learning-to-rank or recommender systems, A/B testing at scale, and ' +
      'low-latency model serving. Nice to have: feature stores, counterfactual ' +
      'evaluation, Kubernetes.',
  },
  {
    id: 'backend-engineer',
    label: 'Backend Engineer',
    role: 'Backend Engineer',
    jobDescription:
      'Backend Engineer, Payments.\n' +
      'You will build and operate the services that move money: invoicing, ' +
      'payment webhooks, reconciliation. Correctness under concurrency matters ' +
      'more here than raw throughput. Requirements: 4+ years backend experience ' +
      'with Python or Go, PostgreSQL, event-driven architectures, idempotency ' +
      'and exactly-once patterns, observability. Nice to have: strangler-fig ' +
      'migrations, property-based testing.',
  },
  {
    id: 'data-engineer',
    label: 'Data Engineer',
    role: 'Data Engineer',
    jobDescription:
      'Data Engineer, Streaming Platform.\n' +
      'Own the event pipelines that feed analytics and ML: Kafka, Flink, ' +
      'Iceberg on S3, roughly 1B events per day. You will drive data contracts ' +
      'with producer teams and keep exactly-once guarantees honest. ' +
      'Requirements: 3+ years data engineering, strong SQL and Python, stream ' +
      'processing experience, lakehouse table formats. Nice to have: dbt, cost ' +
      'optimization on AWS.',
  },
  {
    id: 'frontend-engineer',
    label: 'Frontend Engineer',
    role: 'Frontend Engineer',
    jobDescription:
      'Senior Frontend Engineer — design systems and performance.\n' +
      'You will own a React component library used by six product teams, and ' +
      'the performance budget for the main application. Requirements: 5+ years ' +
      'with React and TypeScript, deep understanding of rendering and bundle ' +
      'performance, accessibility to WCAG AA, and testing strategy for shared ' +
      'components. Nice to have: build tooling, SSR, visual regression testing.',
  },
]
