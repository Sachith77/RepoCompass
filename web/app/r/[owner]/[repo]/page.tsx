import ReportView from "./report-view";

type Props = {
  params: Promise<{ owner: string; repo: string }>;
  searchParams: Promise<{ job?: string }>;
};

export default async function ReportPage({ params, searchParams }: Props) {
  const { owner, repo } = await params;
  const { job } = await searchParams;
  const jobId = job && /^\d+$/.test(job) ? Number(job) : null;
  return <ReportView owner={owner} repo={repo} initialJobId={jobId} />;
}
