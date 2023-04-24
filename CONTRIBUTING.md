# Contributing

Before contributing to this repository, first please discuss the change you wish to make via an
issue, or any other method of communication with the maintainers of this repository.

You can also search this project for issues with the following labels:

| Label                                                                                                                                     | Search Term                               | Description                                                                                                                                                        |
| ----------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| [good-first-issue](https://github.com/bloomberg/memray/search?q=is%3Aissue+is%3Aopen+label%3Agood-first-issue&type=Issues&utf8=%E2%9C%93) | `is:issue is:open label:good-first-issue` | Recommended for first-time contributors! These are well-defined, and allow a user to get familiar with the project's workflow before tackling more complex issues. |
| [help wanted](https://github.com/bloomberg/memray/search?q=is%3Aissue+is%3Aopen+label%3A%22help+wanted%22+&type=Issues&utf8=%E2%9C%93)    | `is:issue is:open label:"help wanted"`    | General issues where contributors help is wanted.                                                                                                                  |
| [question](https://github.com/bloomberg/memray/search?q=is%3Aissue+is%3Aopen+label%3Aquestion&type=Issues&utf8=%E2%9C%93)                 | `is:issue is:open label:question`         | Open discussions to resolve everything from implementation details to desired functionality.                                                                       |

## Contribution Licensing

Since this project is distributed under the terms of an [open source license](LICENSE), contributions that
you make are licensed under the same terms. In order for us to be able to accept your contributions,
we will need explicit confirmation from you that you are able and willing to provide them under
these terms, and the mechanism we use to do this is called a Developer's Certificate of Origin
[(DCO)](https://github.com/bloomberg/.github/blob/main/DCO.md). This is very similar to the process
used by the Linux kernel, Samba, and many other major open source projects.

To participate under these terms, all that you must do is include a line like the following as the
last line of the commit message for each commit in your contribution:

    Signed-Off-By: Random J. Developer <random@developer.example.org>

The simplest way to accomplish this is to add `-s` or `--signoff` to your `git commit` command.

You must use your real name (sorry, no pseudonyms, and no anonymous contributions).

## Documentation

**Public** modules, functions, classes, and methods must be documented using [Python
docstrings][pep 257]. **Non-public** functions and methods must also be documented for defining the
API contract. In addition to being useful for generating documentation, docstrings add clarity when
looking through the source code or using the [built-in help][builtin-help] system, and can be
leveraged in autocompletion by IDEs.

Please see [PEP 257][] for details on semantics and conventions associated with Python docstrings.

### Docstring style

Docstrings must follow [Google style docstrings][google-style]. This docstring style is more
pleasant to read when browsing the source.

## Type hints

All functions and methods should be type annotated. This allows for static analysis and more
intelligent code completion from tools & IDEs.

## Tests

Changes should always include tests. If this is a bug fix it is a good idea to add the tests as the
first commit of the pull request and the changes to fix the issue in subsequent commits to make it
easier to validate it.

## Pull requests

### Linting your code

Before commiting anything, install the pre-commit hooks:

```shell
python3 -m pip install -r requirements-extra.txt
pre-commit install
```

This will ensure that your contribution passes our linting checks.

### PRs should be linked to a GitHub issue

Before opening a pull request to this repository, first please make sure there is a GitHub issue
where your change has been discussed with the maintainers. Mention the issue number in your pull
request description using one of the
[supported keywords](https://help.github.com/articles/closing-issues-using-keywords/). For example,
adding `Closes: #100` in the pull request description will link the PR with the issue and GitHub
will automatically close the issue upon merging it.

Do not include the issue reference in your commit messages however, add it only in the description
of the PR.

<!-- LINKS -->

[pep 257]: https://www.python.org/dev/peps/pep-0257/ "Docstring Conventions"
[pep 484]: https://www.python.org/dev/peps/pep-0484/ "Type Hints"
[google-style]: https://sphinxcontrib-napoleon.readthedocs.io/en/latest/example_google.html "Example Google Style Python Docstrings"
[builtin-help]: https://docs.python.org/3/library/functions.html#help

<!--
vim: tw=99:spell
-->
