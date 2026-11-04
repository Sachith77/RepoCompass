import Parameters from "./parameters";

type Props = { searchParams: Promise<{ repo?: string }> };

const definitions: [string, string][] = [
  [
    "Bots",
    "Excluded everywhere: as PR authors, reviewers, commenters and commit authors. A bot is a GitHub account of type Bot, a login ending in [bot], or one on a configurable list (for commits: the author name, or the login in a GitHub noreply email address) (by default dependabot, renovate, github-actions, k8s-ci-robot and codecov). Deleted accounts and other non-user authors are excluded the same way, rather than guessed at.",
  ],
  [
    "Window and sample",
    "Pull requests created in the 12 months before the snapshot. PRs by bots, deleted accounts and other non-user authors are counted and dropped first. Then up to 250 human PRs are kept per calendar month; a busier month keeps its newest 250, so it is not a random sample, and the report says \"Sampled\" whenever any month was capped.",
  ],
  [
    "Area",
    "A directory. The depth is fitted to each repository: while the largest area holds more than a quarter of the files, it is split one level deeper, up to four levels. Vendored and generated trees are left out: by default vendor, third_party, node_modules, LICENSES and CHANGELOG, matched as top-level directories only. The list is configurable, and each report shows the one it used. Files in the repository root are not an area.",
  ],
  [
    "Area of a PR",
    "The area holding most of the PR's changed files; a tie counts for each tied area. Every changed file is fetched. A PR whose file list cannot be fetched in full is left out of every area figure, and the report says how many.",
  ],
  [
    "Newcomer PR",
    "No merged PR by this author in this repository was created before this one, checked over all of the repository's PR history, not just the window. GitHub's authorAssociation field is not used, because it describes the author today rather than when the PR was opened.",
  ],
  [
    "Mature and merge rate",
    "A PR is mature when it was created at least 30 days before the snapshot and is no longer open. Merge rate = merged / (merged + closed without merging), over mature newcomer PRs only. Open PRs never enter it.",
  ],
  [
    "Repo rate and bands",
    "The repo rate is the same merge rate across the whole repository, including PRs that changed no current area. An area with at least 10 mature newcomer PRs is banded by comparing its 95% Wilson interval with the repo rate: entirely above is \"above repo average\", entirely below is \"below repo average\", overlapping (or touching) is \"no clear difference\". There is no ranking, and areas inside a band are listed alphabetically.",
  ],
  [
    "Distinct authors and concentration",
    "Next to each sample size is the number of different newcomer authors behind it: 12 PRs from 3 people is not 12 PRs from 12. When one author has more than 30% of an area's mature newcomer PRs, the report says the sample is dominated by one contributor.",
  ],
  [
    "Stale open",
    "Newcomer PRs still open more than 90 days after creation. They are outside the merge rate on purpose, so a high stale-open count next to a good merge rate means newcomer PRs are often simply left waiting.",
  ],
  [
    "Response times",
    "Two measures, because each alone misleads. The median time to a response, over newcomer PRs that got one, says how fast answers come but hides PRs nobody answered. The share of mature newcomer PRs with no human response within 30 days catches an area that answers quickly when it answers, but often does not. A formal review is a submitted review by someone other than the author and not a bot; a human response is the earlier of that or a comment by such a person. The two medians are over different sets of PRs (those that got a review, and those that got any response), so the response median can be larger than the review median. The report leads with formal review unless fewer than half of the human PRs at least 30 days old (any author, response times known) got one. A PR merged without any comment or review counts as \"no response\". The summary at the top of a report quotes the repo-wide median (newcomer PRs with complete file lists and known response times that got that response) and the repo-wide share of mature newcomer PRs with no human response within 30 days.",
  ],
  [
    "Areas map",
    "Commits in the last 90 days and 12 months per area (merge commits, bot commits and sweep commits are left out), banded active (a commit in 90 days), steady (commits in 12 months but not 90 days) or dormant. A sweep is a commit touching more than half of all areas and at least five of them, such as a formatting pass. Key contributors and reviewers are counts only: merged PRs authored and reviews submitted. Nobody is called a maintainer or an owner, and no per-person speed is shown.",
  ],
];

const limitations = [
  "Many things affect merge rates besides the area: contributor experience, PR size and complexity, maintainer availability, release cycles and contribution guidelines. A band describes what happened, not how easy an area is, and no area is called objectively easiest.",
  "The newcomer rule sees only pull requests. Someone who contributed by direct push, or before the repository moved to GitHub, counts as a newcomer.",
  "Only the first 20 reviews and 30 comments of each PR are read. When none of them is a human answer and more exist, that PR's response times are marked unknown and left out of the response figures. Reviewer counts are capped at 20 reviews per PR.",
  "Commit authors are counted by email, and no mailmap is applied, so one person with two email addresses counts twice. Commits are dated by committer date.",
  "The report is a snapshot. A cutoff validation on Kludex/starlette, optuna/optuna and sqlfluff/sqlfluff (measured; bands made from PRs mature six months before the snapshot, checked against the months after) could not test the \"above repo average\" band: no such area had at least 10 mature newcomer PRs in both periods. Both \"below repo average\" areas that qualified stayed below (optuna/study, 10 PRs before and 18 after; sqlfluff src, 28 and 113). Two areas are too few for any conclusion, so the bands are not shown to predict anything.",
];

export default async function MethodPage({ searchParams }: Props) {
  const { repo } = await searchParams;
  return (
    <div className="space-y-8">
      <h1 className="text-2xl font-semibold">Method</h1>
      <dl className="space-y-4">
        {definitions.map(([term, text]) => (
          <div key={term}>
            <dt className="font-semibold">{term}</dt>
            <dd className="text-neutral-700">{text}</dd>
          </div>
        ))}
      </dl>
      <section className="space-y-2">
        <h2 className="text-xl font-semibold">Parameters used</h2>
        <p className="text-sm text-neutral-600">
          The numbers above are the defaults. Each analysis stores the parameters it actually ran
          with; pick a repository to see them.
        </p>
        <Parameters repo={repo ?? null} />
      </section>
      <section className="space-y-2">
        <h2 className="text-xl font-semibold">Limitations</h2>
        <ul className="list-disc space-y-1 pl-5 text-neutral-700">
          {limitations.map((text) => (
            <li key={text}>{text}</li>
          ))}
        </ul>
      </section>
    </div>
  );
}
