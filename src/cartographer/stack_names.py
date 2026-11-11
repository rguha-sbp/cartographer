"""The words that name a Terraform stack: the extract reads a stack name from a state path with them, and verify
matches an account label on a diagram to a stack."""

import re

ENVIRONMENTS = {"prod", "production", "prd", "dev", "development", "develop", "test", "tst", "acc", "acceptance", "stag",
                "stage", "stg", "preprod", "qa", "uat", "sandbox", "nonprod", "non", "pre", "env", "live", "int", "integration", "perf"}
IGNORED = {"account", "subscription", "terraform", "aws", "azure", "amazon", "microsoft", *ENVIRONMENTS}
REGION = re.compile(r"\b(us|eu|ap|sa|ca|me|af|il|mx|cn)(-gov|-iso[a-z]?)?-(north|south|east|west|central)[a-z]*-\d+[a-z]?\b")  # us-east-1, us-gov-west-1


def _stem(word: str) -> str:
    """`word` less a plural `s`, then `ing`, then one of a doubled last consonant: `logs` and `logging` are `log`."""
    return re.sub(r"([b-df-hj-np-tv-z])\1$", r"\1", re.sub(r"(ing)?s?$", "", re.sub(r"ies$", "y", word)))


ENVIRONMENT_STEMS = {_stem(w) for w in ENVIRONMENTS}
IGNORED_STEMS = {_stem(w) for w in IGNORED}


def named_after(label: str, stack: str) -> bool:
    """Whether an account label and the stack name have the same words in any order, less IGNORED words, regions and
    account numbers, each word cut to its stem: `networking`, `networking-prod` and
    `prod/networking` name `Networking account`, `Network account`, `AWS networking us-east-1` and
    `Networking (123456789012)`; none names `Shop network account`, `Prod account` or `Net`."""
    words = _stems(label)
    return bool(words) and words in (_stems(stack), _stems(stack.rpartition("/")[2]))  # a state path ends in its name


def names_a_stack(name: str) -> bool:
    """Whether `name` has a word of its own: `staging`, `envs/prod` and `us-east-1/123456789012` have none."""
    return bool(_stems(name))


def _stems(name: str) -> list[str]:
    """The words of `name` that are not IGNORED, AWS regions or numbers, each cut to its stem, sorted. A name with no
    other word keeps a variant of an IGNORED word that is no environment: `accounting` and `subscriptions` are names."""
    words = [w for w in re.findall(r"[a-z0-9]+", REGION.sub(" ", name.lower().replace("_", "-"))) if not w.isdigit()]
    own = [s for w in words if (s := _stem(w)) and s not in IGNORED_STEMS]
    return sorted(own or (_stem(w) for w in words if w not in IGNORED and _stem(w) not in ENVIRONMENT_STEMS))
