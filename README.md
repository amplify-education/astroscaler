# AstroScaler
[![Codacy Badge](https://api.codacy.com/project/badge/Grade/3f113e10586240a2877b7535f4bef560)](https://www.codacy.com/app/CFER/astroscaler?utm_source=github.com&amp;utm_medium=referral&amp;utm_content=amplify-education/astroscaler&amp;utm_campaign=Badge_Grade)
[![Build Status](https://travis-ci.org/amplify-education/astroscaler.svg?branch=master)](https://travis-ci.org/amplify-education/astroscaler)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](https://raw.githubusercontent.com/amplify-education/data_kennel/master/LICENSE)
[![Codacy Badge](https://api.codacy.com/project/badge/Coverage/3f113e10586240a2877b7535f4bef560)](https://www.codacy.com/app/CFER/astroscaler?utm_source=github.com&utm_medium=referral&utm_content=amplify-education/astroscaler&utm_campaign=Badge_Coverage)

AstroScaler is an AWS Lambda function that dynamically scales AWS ASGs and Spotinst Elastigroups based on system and application metrics. It works in conjunction with Datadog monitors to determine when a scaling activity should happen by periodically querying for the monitors that are in alert state. These Datadog monitors must be tagged with various information so that AstroScaler can derive the correct policy to execute.

# About Amplify
Amplify builds innovative and compelling digital educational products that empower teachers and students across the country. We have a long history as the leading innovator in K-12 education - and have been described as the best tech company in education and the best education company in tech. While others try to shrink the learning experience into the technology, we use technology to expand what is possible in real classrooms with real students and teachers.

Learn more at https://www.amplify.com

# Getting Started
## Prerequisites
AstroScaler requires the following to be installed:
```
python >= 2.7.12
```

For development, `tox>=2.9.1` is recommended.

## Installing/Building
AstroScaler is setup through tox, so simply run `tox`.

## Running Tests
AstroScaler uses tox, so running `tox` will automatically execute linters as well as the unit tests. You can also run functional and integration tests by using the -e argument.

Ex: `tox -e lint,py27-unit,py27-integration`.

To see all the available options, run `tox -l`.

## Deployment
We recommend using the [Serverless Framework](https://serverless.com/) for deploying AstroScaler. Included in the repo is a `serverless.example.yml` file that can be extended with your own customizations.

## Configuration
AstroScaler accepts configuration from two sources, environment variables and S3.

### Environment Variables
AstroScaler reads several environment variables:

* astroscaler_global_filters
    * An initial level of filtering for all monitors that AstroScaler evaluates. AstroScaler will check for a tag on the monitor matching the filters specified in this environment variable. Multiple filters can be specified, separated by commas. Example: environment:ci,scalable:true
* astroscaler_config_bucket
    * The S3 bucket that holds credentials for AstroScaler to use when interacting with Datadog / Spotinst.

### S3 Configurations
Currently, AstroScaler looks up a few paths in the provided `astroscaler_config_bucket`. This is done to make it easier to rotate these credentials.

* app_auth/datadog/api_key
    * The API Key to use when connecting to Datadog.
* app_auth/datadog/astroscaler_app_key
    * The APP Key to use when connecting to Datadog.
* spotinst/temp_access_token
    * The token to use when connecting to Spotinst.

## Activation
AstroScaler is currently activated via Datadog Monitors. When a monitor enters alert state, AstroScaler checks the tags of the monitor to determine what to do. There are currently two types of policies that AstroScaler can activate, either an `AWS Policy` or a `Self Policy`.

### AWS Policy
AWS policies are policies that are managed by AWS, as part of an AutoScalingGroup. AstroScaler simply executes these policies and relies on AWS to correctly apply the policy's adjustments and respect the policy's cooldown timers.

A monitor for executing an AWS policy needs the following tags:

* monitor_type
    * The type of the monitor should always be `monitor_type:astroscaler`.
* astroscaler\_group\_tags
    * This is a comma separated list of group tags that will determine the group(s) a policy will be fired upon. The DataDog monitor needs to have all these tags, which will be matched against the very same tags in groups.<br />
    Example: `astroscaler_group_tags:environment,hostclass,team`.<br />
    _Note: If no `astroscaler_group_tags` is provided, by default it will try to match  `environment` and `hostclass` group tags._
* policy_name
    * The name of the AWS policy to fire. Ex: `policy_name:up`.
    
### Self Policy
Self policies are policies that are interpreted and executed by AstroScaler. AstroScaler is responsible for correctly applying the adjustment as well as respecting the designated cooldown.

A monitor for executing self policies needs the following tags:

* monitor_type
    * The type of the monitor should always be `monitor_type:astroscaler`.
* astroscaler\_group\_tags
    * This is a comma separated list of group tags that will determine the group(s) a policy will be fired upon. The DataDog monitor needs to have all these tags, which will be matched against the very same tags in groups.<br />
    Example: `astroscaler_group_tags:environment,hostclass,team`.<br />
    _Note: If no `astroscaler_group_tags` is provided, by default it will try to match  `environment` and `hostclass` group tags._
* policy_adjustment
    * How to adjust the current sizing of the group. An unsigned integer is the exact amount of instances desired.
      Ex. `7` would set the number of instances to 7, irregardless of the starting size. A signed integer is the number of instances to add or remove from the group. Ex. `-2` would remove two instances from the group while `+3` would add three instances. A signed percentage will modify the group by that percentage. Ex. `+100%` will double the size of the group while `-10%` will remove ten percent of the instances from that group. Finally, an unsigned percentage will behave the same as a positive percentage. **Percentage based adjustments will always round the magnitude of their adjustment upwards.** For example, AstroScaler will perform the following adjustments: `10 - 15% = 8` and `25 + 5% = 27`. Final example: `policy_adjustment:+50%`.
* policy_cooldown
    * The number of seconds to wait between executions of the policy. If not provided, it is defaulted to "600".
    Ex: `policy_cooldown:180`.

# Responsible Disclosure
If you have any security issue to report, contact project maintainers privately.
You can reach us at <github@amplify.com>

# Contributing
We welcome pull requests! For your pull request to be accepted smoothly, we suggest that you:
1. For any sizable change, first open a GitHub issue to discuss your idea.
2. Create a pull request.  Explain why you want to make the change and what it’s for.
We’ll try to answer any PR’s promptly.
