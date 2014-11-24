# Overview

Harold and Harold's Code Salon are tools for coordinating software development,
code review, and deployment. They were made for reddit.com's dev team to use
and have grown over the years.

## Installation

Harold's `setup.py` will install a base system. Configuration of the salon web
interface is not yet documented.

## Configuration

See [example.ini](example.ini) for a sample configuration with annotations.

## API

If the HTTP plugin is enabled, harold will present an HTTP API which allows
various actions to be commanded remotely. A simple python command API wrapper
can be found in https://github.com/spladug/wessex.

## License

The Harold code itself is released under the BSD 3-clause license.  Various 3rd
party components have different licenses and all of this can be found in
[LICENSE](LICENSE).
