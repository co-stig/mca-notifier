# MCA Notifier

There's a network of swimming centers in France, managed by the online platform
[Mon Centre Aquatique](https://moncentreaquatique.com). Each center offers a range
of sport activities like Aquaboxing, Aquabiking, etc. Unfortunately, some people
abuse the system by subscribing to all activities they can find, and then canceling
at the last moment. The online platform does not penalize them for doing so. As a
result, people who are genuinely interested in going to the swimming pool, are
unable to find free time slots, unless they check the website every N minutes.

This script notifies about free swimming slots at MCA for the given activities, as
soon as they appear on their website. It is designed to run on the server and uses
[Pushover](https://pushover.net/) service for delivering notifications.

I'm really not proud of the code quality, wrote this script over the weekend to
address my wife's frustration with MCA. Some of the ugliness is due to MCA's website
rudimentary backend, which relies on the user sessions (the requests must go in the
correct order), and only returns `text/html` content type.

## Improvements

- Split code into files
- Fetch activity names for the given IDs
- Generate random user session IDs
- Use proper logging, including exceptions
- Notify about exceptions
- Add Build and Run sections to this README
