# Call for Participation (CfP) #
There are 3 types of proposal which is accepted to the CfP:

* Talks (and performances) anything that has a presenter on a stage in front of an audience
* Workshops (and games etc) a tent, an instructor and attendees working togeth
* Installations weekend long things

## Review process ##

1. Submission
2. Sanity checks (in order to reject, e.g. hate speech or spam)
3. Anonymisation
4. Review (score 0, 1 or 2)
5. Judging (all submissions are ranked according to Majority judgement)
    * Highest ranked submissions accepted
    * Low ranked submissions added to next round

## Tables ##

There are 4 tables used in the CfP:

* proposal - the information received from the users
* category - used to group talk proposals for reviewers
* CFPmessage - implements a simple messaging system between submitters and admin
* CFPVotes - votes from reviewers against a proposal

### Polymorphic tables ###

The different types of submission (workshop, installation, talk) are represented as polymorphic entries in the proposal table, this means they can be operated on as separate tables (e.g. as `TalkProposal.query.all()`) or as entries of the same table (e.g. as `Proposal.query.all()`).

## State Machines ##

### Proposal ###
Submissions flow through the following state machine:

* 'edit' - State that indicates the proposal isn't new but can be edited
* 'new' - Initial state of a proposal
* 'locked' - After two days 'new' proposals become 'locked'. 'Locked' proposals are then checked and are either:
    * 'checked' - The proposal is fine and is ready to be anonymised
    * 'rejected' - There is some problem with the proposal, the admin can then work to resolve this with the submitter.
* 'anonymised' - 'checked' proposals then have their title and description checked for identifying information which might bias the reviewers.
    * 'anon-blocked' - if for some reason the proposal can't be anonymised then it is marked as such and the admin can work with the submitter to resolve the problem
* 'reviewed' - when a round of votes is closed proposals that have the minimum number of votes cast against them are marked as 'reviewed'
* 'accepted' - 'reviewed' proposals that receive a high enough score are marked as accepted and are ready to be added to the schedule
* 'finished' - 'accepted' proposals that have had their details checked and a time slot (if appropriate) organised are marked as 'finished'.

The ideal flow is something like:
new > locked > checked > anonymised > reviewed > accepted > finished

### Votes ###

The vote state machine mainly carries semantic information about the vote. The states are:

* 'new' - the initial state of the vote (in theory it should never be in this state)
* 'voted' - the reviewer has voted on the proposal
* 'recused' - the reviewer has a conflict of interest, in theory a vote never leaves this state although this can be over-ridden.
* 'blocked' - the reviewer has questions or some other problem with the proposal and is awaiting a response to their note from the admin
* 'resolved' - blocked votes are marked as 'resolved' once the admin and reviewer are happy that the reviewer can now vote on the proposal (recused votes can be forced into this state if need-be)
* 'stale' - if there is a significant change to a proposal then the admin can set all votes cast against it as 'stale' in order to require a new vote from reviewers.



