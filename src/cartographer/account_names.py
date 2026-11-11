"""Whether an account label on a diagram names a Terraform stack."""

import re

ENVIRONMENTS = {"prod", "production", "prd", "dev", "development", "develop", "test", "tst", "acc", "acceptance", "stag",
                "stage", "stg", "preprod", "qa", "uat", "sandbox", "nonprod", "env"}
IGNORED = {"account", "subscription", "terraform", "aws", "azure", "amazon", "microsoft", *ENVIRONMENTS}
REGION = re.compile(r"\b[a-z]{2}(-[a-z]+)?-(north|south|east|west|central)[a-z]*-\d+[a-z]?\b")  # us-east-1, us-gov-west-1


def _stem(word: str) -> str:
    """`word` less a plural `s`, then `ing`, then one of a doubled last consonant: `logs` and `logging` are `log`."""
    return re.sub(r"([b-df-hj-np-tv-z])\1$", r"\1", re.sub(r"(ing)?s?$", "", word))


IGNORED_STEMS = {_stem(w) for w in IGNORED}


def named_after(label: str, stack: str) -> bool:
    """Whether an account label and the stack name have the same words in any order, less IGNORED words, regions and
    account numbers, each word cut to its stem: `networking`, `networking-prod` and
    `prod/networking` name `Networking account`, `Network account`, `AWS networking us-east-1` and
    `Networking (123456789012)`; none names `Shop network account`, `Prod account` or `Net`."""
    words = _stems(label)
    return bool(words) and words == _stems(stack)


def _stems(name: str) -> list[str]:
    """The words of `name` that are not IGNORED, AWS regions or numbers, each cut to its stem, sorted."""
    words = re.findall(r"[a-z0-9]+", REGION.sub(" ", name.lower().replace("_", "-")))
    return sorted(s for w in words if not w.isdigit() and (s := _stem(w)) and s not in IGNORED_STEMS)
