# blog-aws-monitor-rss-feeds
This repository contains code for deploying a solution to monitor RSS feeds for keywords. When a match is found, a notification is sent to a slack channel, with details about the matched item.

## Preparation
Clone this repository using the following command.
```
git clone https://github.com/nivleshc/blog-aws-monitor-rss-feeds.git
```

Export the following environment variables.

```
export AWS_PROFILE_NAME={aws profile to use}

export AWS_S3_BUCKET_NAME={name of aws s3 bucket to store SAM artefacts in}

export SLACK_WEBHOOK_URL={slack webhook url to use for sending slack notifications}
```

## Commands

For help, run the following command:
```
make
```
To deploy the code in this repository to your AWS account, use the following steps:

```
make package
make deploy
```

If you make any changes to **template.yaml**, first validate the changes by using the following command (validation is not required if you change other files):
```
make validate
```

After validation is successful, use the following command to deploy the changes:
```
make update
```
