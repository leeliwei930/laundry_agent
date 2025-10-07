package main

import (
	"os"

	"github.com/aws/aws-cdk-go/awscdk/v2"
	"github.com/aws/aws-cdk-go/awscdk/v2/awsec2"
	"github.com/aws/aws-cdk-go/awscdk/v2/awsiam"
	"github.com/aws/aws-cdk-go/awscdk/v2/awslambda"

	// "github.com/aws/aws-cdk-go/awscdk/v2/awssqs"
	"github.com/aws/constructs-go/constructs/v10"
	"github.com/aws/jsii-runtime-go"
)

type VPCStackProps struct {
	awscdk.StackProps
}

type DeploymentStackProps struct {
	awscdk.StackProps
}

func NewDeploymentStack(scope constructs.Construct, id string, props *DeploymentStackProps) awscdk.Stack {
	var sprops awscdk.StackProps
	if props != nil {
		sprops = props.StackProps
	}
	stack := awscdk.NewStack(scope, &id, &sprops)

	// The code that defines your stack goes here

	// example resource
	// queue := awssqs.NewQueue(stack, jsii.String("DeploymentQueue"), &awssqs.QueueProps{
	// 	VisibilityTimeout: awscdk.Duration_Seconds(jsii.Number(300)),
	// })

	return stack
}

func NewVPCStack(scope constructs.Construct, id string, props *VPCStackProps) (awscdk.Stack, awsec2.Vpc) {

	var sprops awscdk.StackProps
	if props != nil {
		sprops = props.StackProps
	}
	stack := awscdk.NewStack(scope, &id, &sprops)

	vpc := awsec2.NewVpc(stack, jsii.String("homelabVpc"), &awsec2.VpcProps{
		EnableDnsHostnames:     jsii.Bool(true),
		EnableDnsSupport:       jsii.Bool(true),
		IpAddresses:            awsec2.IpAddresses_Cidr(jsii.String("172.31.0.0/16")),
		Ipv6Addresses:          awsec2.Ipv6Addresses_AmazonProvided(),
		NatGateways:            jsii.Number(0),
		MaxAzs:                 jsii.Number(3),
		DefaultInstanceTenancy: awsec2.DefaultInstanceTenancy_DEFAULT,
		CreateInternetGateway:  jsii.Bool(true),
		IpProtocol:             awsec2.IpProtocol_DUAL_STACK,
		SubnetConfiguration: &[]*awsec2.SubnetConfiguration{
			{
				Name:                        jsii.String("homelabVpcPrivateSubnet"),
				SubnetType:                  awsec2.SubnetType_PRIVATE_WITH_EGRESS,
				Ipv6AssignAddressOnCreation: jsii.Bool(true),
				CidrMask:                    jsii.Number(22),
			},
			{
				Name:                        jsii.String("homelabVpcPublicSubnet"),
				SubnetType:                  awsec2.SubnetType_PUBLIC,
				Ipv6AssignAddressOnCreation: jsii.Bool(true),
				CidrMask:                    jsii.Number(22),
				MapPublicIpOnLaunch:         jsii.Bool(false),
			},
		},
	})

	return stack, vpc
}

func main() {
	defer jsii.Close()

	app := awscdk.NewApp(nil)

	vpcStack, _ := NewVPCStack(app, "HomeLabVPC", &VPCStackProps{
		awscdk.StackProps{
			Env: env(),
		},
	})
	stack := NewDeploymentStack(app, "CamFootageActivitiesAnalyserAgentDeploymentStack", &DeploymentStackProps{
		awscdk.StackProps{
			Env: env(),
		},
	})

	dependenciesLayer := awslambda.NewLayerVersion(stack, jsii.String(
		"camFootageActivitiesAnalyserAgentDependenciesLayer",
	), &awslambda.LayerVersionProps{
		Code:               awslambda.AssetCode_FromAsset(jsii.String("../build/dependencies.zip"), nil),
		CompatibleRuntimes: &[]awslambda.Runtime{awslambda.Runtime_PYTHON_3_13()},
	})

	camFootageActivitiesAnalyserAgentFunc := awslambda.NewFunction(stack, jsii.String("camFootageActivitiesAnalyserAgent"), &awslambda.FunctionProps{
		Code: awslambda.AssetCode_FromAsset(jsii.String("../build/functions.zip"),
			nil,
		),
		MemorySize: jsii.Number(2048),
		Timeout:    awscdk.Duration_Seconds(jsii.Number(60)),
		Handler:    jsii.String("agent.handler"),
		Runtime:    awslambda.Runtime_PYTHON_3_13(),
		Layers:     &[]awslambda.ILayerVersion{dependenciesLayer},
		Vpc: awsec2.Vpc_FromLookup(vpcStack, jsii.String("lambdaVpc"), &awsec2.VpcLookupOptions{
			VpcName: jsii.String("HomeLabVPC/homelabVpc"),
		}),
		Architecture:            awslambda.Architecture_ARM_64(),
		AllowAllIpv6Outbound:    jsii.Bool(true),
		Ipv6AllowedForDualStack: jsii.Bool(true),
		AllowPublicSubnet:       jsii.Bool(true),
		VpcSubnets: &awsec2.SubnetSelection{
			SubnetType: awsec2.SubnetType_PRIVATE_WITH_EGRESS,
		},
	})

	camFootageActivitiesAnalyserAgentFunc.AddToRolePolicy(awsiam.NewPolicyStatement(&awsiam.PolicyStatementProps{
		Actions: &[]*string{
			jsii.String("bedrock:InvokeModel"),
			jsii.String("bedrock:InvokeModelWithResponseStream"),
			jsii.String("bedrock:ListInferenceProfiles"),
			jsii.String("bedrock:GetInferenceProfile"),
		},
		Resources: &[]*string{jsii.String("*")},
	}))

	app.Synth(nil)
}

// env determines the AWS environment (account+region) in which our stack is to
// be deployed. For more information see: https://docs.aws.amazon.com/cdk/latest/guide/environments.html
func env() *awscdk.Environment {
	// If unspecified, this stack will be "environment-agnostic".
	// Account/Region-dependent features and context lookups will not work, but a
	// single synthesized template can be deployed anywhere.
	//---------------------------------------------------------------------------
	// return nil

	// Uncomment if you know exactly what account and region you want to deploy
	// the stack to. This is the recommendation for production stacks.
	//---------------------------------------------------------------------------
	// return &awscdk.Environment{
	//  Account: jsii.String("123456789012"),
	//  Region:  jsii.String("us-east-1"),
	// }

	// Uncomment to specialize this stack for the AWS Account and Region that are
	// implied by the current CLI configuration. This is recommended for dev
	// stacks.
	//---------------------------------------------------------------------------
	return &awscdk.Environment{
		Account: jsii.String(os.Getenv("CDK_DEFAULT_ACCOUNT")),
		Region:  jsii.String(os.Getenv("CDK_DEFAULT_REGION")),
	}
}
