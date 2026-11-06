import { Label } from "@/components/ui";

import Parameters from "./parameters";

type Props = { searchParams: Promise<{ repo?: string }> };

const definitions: [string, string][] = [
  [
    "Bots",
    "Excluded everywhere: as PR authors, reviewers, commenters and commit authors. A bot is a GitHub account of type Bot, a login ending in [bot], or a login on a configurable list (by default dependabot, renovate, github-actions, k8s-ci-robot and codecov). For commits, the author name and the part of the email address before the @ (the login, for a GitHub noreply address) are checked the same way. Deleted accounts and other non-user authors are excluded too, rather than guessed at.",
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
    "A PR is mature when it was created at least 30 days before the snapshot and is no longer open; the report calls these finished PRs. Merge rate = merged / (merged + closed without merging), over mature newcomer PRs only. Open PRs never enter it.",
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
  "Only the first 20 reviews and 30 comments of each PR are read. When either list was cut short with no human answer in it, that PR's response times are marked unknown and left out of the response figures. Reviewer counts are capped at 20 reviews per PR.",
  "Commit authors are counted by email, and no mailmap is applied, so one person with two email addresses counts twice. Commits are dated by committer date.",
  "The report is a snapshot. A cutoff validation (measured) re-made the bands from data before a cutoff and checked them against what happened after it: with 12-month analyses and a cutoff six months back on Kludex/starlette, optuna/optuna and sqlfluff/sqlfluff, no \"above repo average\" area had at least 10 mature newcomer PRs in both periods, and both \"below repo average\" areas stayed below (optuna/study, 10 PRs before and 18 after; sqlfluff src, 28 and 113); with 24-month analyses and a cutoff a year back on optuna/optuna, sqlfluff/sqlfluff, pydantic/pydantic and fastapi/fastapi, one \"above\" area (pydantic docs, 30 and 67) and one \"below\" area (the pydantic package, 71 and 287) qualified, and both held. Four areas are too few for any conclusion, so the bands are not shown to predict anything.",
];

const slug = (text: string) => text.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, "");

export default async function MethodPage({ searchParams }: Props) {
  const { repo } = await searchParams;
  const contents = [
    ...definitions.map(([term]) => ({ id: slug(term), title: term })),
    { id: "parameters", title: "Parameters used" },
    { id: "limitations", title: "Limitations" },
  ];
  return (
    <div className="lg:grid lg:grid-cols-[13rem_minmax(0,680px)] lg:gap-16">
      <nav aria-label="On this page" className="hidden lg:block">
        <div className="sticky top-8 space-y-3">
          <Label>On this page</Label>
          <ol className="space-y-1.5 border-l border-line text-small">
            {contents.map((c) => (
              <li key={c.id}>
                <a href={`#${c.id}`} className="-ml-px block border-l border-transparent pl-3 text-muted hover:border-ink hover:text-ink">
                  {c.title}
                </a>
              </li>
            ))}
          </ol>
        </div>
      </nav>

      <article className="space-y-12">
        <header className="space-y-3">
          <Label>Method</Label>
          <h1 className="font-serif text-display font-semibold">How the numbers are made</h1>
          <p className="text-lead text-muted">
            Every figure in a report comes from the repository&apos;s public git history and pull
            requests. These are the definitions, the parameters each analysis used, and what the
            numbers cannot tell you.
          </p>
        </header>

        <section className="space-y-8">
          <h2 className="border-b border-line pb-2 font-serif text-title font-semibold">Definitions</h2>
          {definitions.map(([term, text]) => (
            <div key={term} id={slug(term)} className="scroll-mt-8 space-y-1.5">
              <h3 className="font-serif text-heading font-semibold">{term}</h3>
              <p className="leading-relaxed">{text}</p>
            </div>
          ))}
        </section>

        <section id="parameters" className="scroll-mt-8 space-y-3">
          <h2 className="border-b border-line pb-2 font-serif text-title font-semibold">Parameters used</h2>
          <p className="text-muted">
            The numbers above are the defaults. Each analysis stores the parameters it actually ran
            with; pick a repository to see them.
          </p>
          <Parameters repo={repo ?? null} />
        </section>

        <section id="limitations" className="scroll-mt-8 space-y-3">
          <h2 className="border-b border-line pb-2 font-serif text-title font-semibold">Limitations</h2>
          <ul className="space-y-3">
            {limitations.map((text) => (
              <li key={text} className="border-l-2 border-line pl-4 leading-relaxed">
                {text}
              </li>
            ))}
          </ul>
        </section>
      </article>
    </div>
  );
}
