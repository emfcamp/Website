# Call for Participation (CfP) #
There are 3 types of proposal which is accepted to the CfP:

* Talks (and performances) anything that has a presenter on a stage in front of an audience
* Workshops (and games etc) a tent, an instructor and attendees working togeth
* Installations weekend long things

## Review process ##

1. Submission
2. Sanity checks (in order to reject, e.g. hate speech)
3. Anonymisation
4. Review (score 0, 1 or 2)
5. Judging (all submissions are ranked by Majority Vote)
    * Highest ranked submissions accepted
    * Low ranked submissions added to next round

## Tables ##

There are three tables used in the CfP:

* proposal - the information received from the users
* review_proposal - anonymised proposals for scoring
* category - used to group talk proposals for reviewers

### Polymorphic tables ###

The different types of submission (workshop, installation, talk) are represented as polymorphic entries in the proposal table, this means they can be operated on as separate tables (e.g. as `TalkProposal.query.all()`) or as entries of the same table (e.g. as `Proposal.query.all()`).

## State Machine ##

Submissions flow through the following state machine:

1. 'New' - For 2 days submissions are marked as new, in this time the user can edit their submission
2. 'Locked' - After 2 days new submissions are marked as locked at which point they are sanity-checked
3. 'Anonymisation' - Submissions that pass the sanity check are ready to be anonymised
4. 'Review' - Submissions to be reviewed and scored
5. 'Judged' - The judge closes the round and the reviewed submissions set to this state
6. 'Accepted' - Submissions that are accepted are marked with this, otherwise they remain 'Judged'.

Special state: 'Rejected' this is only used for submissions that are rejected for e.g. violation of the CoC

