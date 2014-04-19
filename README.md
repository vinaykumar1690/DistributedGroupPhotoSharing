DistributedGroupPhotoSharing
============================

A Distributed photo sharing application that uses the two phase commit protocol to deal with server failures

This repo has the source code for a project assigned for the course "15-749 Engineering Distributed Systems" 
offered at Carnegie Mellon University. Copying code from this repo is strictly prohibited.

A Web application to support a group photo session that works as follows:
• One user creates a new web page for an event to collect photos from a group of users.
• Through out-of-band notification, such as email or chat, the event creator invites other users to submit
photographs for the group photo.
• Each of the invited users can submit one or more photos.
• After each photo is uploaded, a new group montage is generated and may be viewed by users who have
submitted a photo.
• If a user likes the montage he may start a limited-duration voting period by casting a vote.
• Each user must then either accept the montage (commit), explicitly abort/cancel, or let the vote period
time-out (abort). If not all votes have been collected at the end of the voting period the transaction is
aborted.
• Once a vote has been cast, no more photos may be added to the event unless the current transaction
has been aborted, either by timeout or a nay vote.
• Only when all users have accepted, the montage is considered committed and made publicly available.
• A user must not be allowed to cast a vote for a montage that has been superseded by a newer version.
For simplicity, you can assume fixed limits:
• On the number of contributors (say to class size, total 6-10 people).
• On the duration of the voting period.
• Users are identified by a browser cookie.

Dealing with failures
Every node participating in 2 phase commit has to write its intentions and commitments to stable storage.
As far as the participants are concerned, we have to rely on the users who submitted photos to navigate back
to the group photo session web page after a browser or computer crash.
Every user should be given the option to accept or reject the publication of the group picture. If a user
accepts, this intent must be stored persistently and the user is no longer allowed to change his mind. If
any user chooses to reject, the complete transaction should be aborted. As long as nobody has rejected,
the photograph and intent of users who have decided to accept should persist across application and/or
server restarts. If unanimous consent is not reached within a (short, one or two minute) time interval the
transaction is to be aborted.
The coordinator has to persistently store transaction state, submitted photos, the list of participating users
and accepted votes. This data will need to survive application failures, network failures and server failures.
Really think hard about where you store this transaction state (plain file, SQLite, MySQL, Redis) and what
the effect would be if the server loses power, network connectivity, or if the application unexpectedly crashes
in the middle of processing an operation. Once a decision is taken by the coordinator, it has to follow through
with that decision. Also remember that losing network connectivity may imply losing access to a MySQL
server.


A distributed version of the Web application
A simple web application works up to a few dozen events and a couple of hundred users. But imagine your
application is so awesome that overnight it becomes a runaway success and gets used for thousands of events
by hundreds of thousands of users.
You will implement a replicated service where each ‘site’ acts as a full read-write replica.
Multiple locations are simulated by running three or four instances of your web service on different local
ports. Port 8000 could be an instance running at a west-coast data center, 8001 on the east-coast, etc. These
server instances may expose ‘internal’ http/api calls that they use to communicate with each other.
When a new event is created on a server it becomes the master for the overall voting process, it is responsible
for creating ‘shadow’ events on all other instances. Use two phase commit to make sure that all instances
have successfully created the event before allowing photo upload and voting.
Invited users may connect to any instance and are expected to use that same instance during the remaining
upload/voting period, i.e. assume that DNS or routing is used to redirect users to their geographically closest
data center. When a photo is uploaded the upload site becomes a two phase master to ensure the photo
is distributed to all other instances using two phase commit to make sure the voting process has not been
started anywhere.
When a submitter votes, the vote must be persistently recorded locally, but it does not have to be immediately
propagated to the other instances. When all submitters at an instance have voted, the vote master may
be informed of this. When all instances report that the votes are in, or the voting period ends, the vote
master is responsible for both collecting the votes and distributing the results. The master must check with
all instances and make sure that all submitters have voted to accept the collection of photos. If all users have
chosen to commit, then the master has to use a two phase commit to announce to all instances that the event
may be published, otherwise an abort must be propagated.
Assume that at any time an instance may disappear because of application, network or server errors and that
operations will have to be retried until they have been acknowledged. The master must make sure to retry
operations (at least once semantics). The other instances must be prepared to handle duplicated operations.
