# sns.tf
resource "aws_sns_topic" "review_notifications" {
  name = "patient-deid-review-notifications"
}

resource "aws_sns_topic_subscription" "reviewer_email" {
  topic_arn = aws_sns_topic.review_notifications.arn
  protocol  = "email"
  endpoint  = "huuthang.khuat21@gmail.com"
}