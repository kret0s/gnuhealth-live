Account Credit Limit
####################

The account_credit_limit module manages credit limit of parties. A "Credit
Limit Amount" is added on Party. The module allows to check for a party:

    * If an amount will exceed his limit.
    * If a dunning has reached a limit level.

and then raises an error message or a warning if the user is part of the
"Account Credit Limit" group.
