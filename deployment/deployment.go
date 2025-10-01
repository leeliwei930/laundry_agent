package main

import (
	"github.com/aws/aws-cdk-go/awscdk/v2"
	"github.com/aws/aws-cdk-go/awscdk/v2/awsec2"

	// "github.com/aws/aws-cdk-go/awscdk/v2/awssqs"
	"github.com/aws/constructs-go/constructs/v10"
	"github.com/aws/jsii-runtime-go"
)

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

func NewVPC(scope constructs.Construct, id string) awsec2.Vpc {

	vpc := awsec2.NewVpc(scope, jsii.String("agent_vpc"), &awsec2.VpcProps{
		MaxAzs:        jsii.Number(3),
		IpAddresses:   awsec2.IpAddresses_Cidr(jsii.String("172.31.0.0/16")),
		Ipv6Addresses: awsec2.Ipv6Addresses_AmazonProvided(),
		IpProtocol:    awsec2.IpProtocol_DUAL_STACK,
	})

	// Private subnets
	awsec2.NewCfnSubnet(scope, jsii.String("agent_vpc_private_subnet_5a"), &awsec2.CfnSubnetProps{
		VpcId:                       vpc.VpcId(),
		CidrBlock:                   jsii.String("172.31.1.0/24"),
		AvailabilityZone:            jsii.String("ap-southeast-5a"),
		MapPublicIpOnLaunch:         jsii.Bool(false),
		AssignIpv6AddressOnCreation: jsii.Bool(true),
	})
	awsec2.NewCfnSubnet(scope, jsii.String("agent_vpc_private_subnet_5b"), &awsec2.CfnSubnetProps{
		VpcId:                       vpc.VpcId(),
		CidrBlock:                   jsii.String("172.31.3.0/24"),
		AvailabilityZone:            jsii.String("ap-southeast-5b"),
		MapPublicIpOnLaunch:         jsii.Bool(false),
		AssignIpv6AddressOnCreation: jsii.Bool(true),
	})
	awsec2.NewCfnSubnet(scope, jsii.String("agent_vpc_private_subnet_5c"), &awsec2.CfnSubnetProps{
		VpcId:                       vpc.VpcId(),
		CidrBlock:                   jsii.String("172.31.5.0/24"),
		AvailabilityZone:            jsii.String("ap-southeast-5c"),
		MapPublicIpOnLaunch:         jsii.Bool(false),
		AssignIpv6AddressOnCreation: jsii.Bool(true),
	})

	awsec2.NewCfnSubnet(scope, jsii.String("agent_vpc_public_subnet_5a"), &awsec2.CfnSubnetProps{
		VpcId:                       vpc.VpcId(),
		CidrBlock:                   jsii.String("172.31.2.0/24"),
		AvailabilityZone:            jsii.String("ap-southeast-5a"),
		AssignIpv6AddressOnCreation: jsii.Bool(true),
	})
	awsec2.NewCfnSubnet(scope, jsii.String("agent_vpc_public_subnet_5b"), &awsec2.CfnSubnetProps{
		VpcId:                       vpc.VpcId(),
		CidrBlock:                   jsii.String("172.31.4.0/24"),
		AvailabilityZone:            jsii.String("ap-southeast-5b"),
		AssignIpv6AddressOnCreation: jsii.Bool(true),
	})
	awsec2.NewCfnSubnet(scope, jsii.String("agent_vpc_public_subnet_5c"), &awsec2.CfnSubnetProps{
		VpcId:                       vpc.VpcId(),
		CidrBlock:                   jsii.String("172.31.6.0/24"),
		AvailabilityZone:            jsii.String("ap-southeast-5c"),
		AssignIpv6AddressOnCreation: jsii.Bool(true),
	})

	awsec2.NewCfnRouteTable(scope, jsii.String("agent_vpc_private_rtb"), &awsec2.CfnRouteTableProps{
		VpcId: vpc.VpcId(),
	})
	awsec2.NewCfnSubnetRouteTableAssociation(scope, jsii.String("agent_vpc_private_subnet_5a_route_table_association"), &awsec2.CfnSubnetRouteTableAssociationProps{
		SubnetId:     jsii.String("agent_vpc_private_subnet_5a"),
		RouteTableId: jsii.String("agent_vpc_private_rtb"),
	})
	awsec2.NewCfnSubnetRouteTableAssociation(scope, jsii.String("agent_vpc_private_subnet_5b_route_table_association"), &awsec2.CfnSubnetRouteTableAssociationProps{
		SubnetId:     jsii.String("agent_vpc_private_subnet_5b"),
		RouteTableId: jsii.String("agent_vpc_private_rtb"),
	})
	awsec2.NewCfnSubnetRouteTableAssociation(scope, jsii.String("agent_vpc_private_subnet_5c_route_table_association"), &awsec2.CfnSubnetRouteTableAssociationProps{
		SubnetId:     jsii.String("agent_vpc_private_subnet_5c"),
		RouteTableId: jsii.String("agent_vpc_private_rtb"),
	})

	awsec2.NewCfnRouteTable(scope, jsii.String("agent_vpc_public_rtb"), &awsec2.CfnRouteTableProps{
		VpcId: vpc.VpcId(),
	})
	awsec2.NewCfnSubnetRouteTableAssociation(scope, jsii.String("agent_vpc_public_subnet_5a_route_table_association"), &awsec2.CfnSubnetRouteTableAssociationProps{
		SubnetId:     jsii.String("agent_vpc_public_subnet_5a"),
		RouteTableId: jsii.String("agent_vpc_public_rtb"),
	})
	awsec2.NewCfnSubnetRouteTableAssociation(scope, jsii.String("agent_vpc_public_subnet_5b_route_table_association"), &awsec2.CfnSubnetRouteTableAssociationProps{
		SubnetId:     jsii.String("agent_vpc_public_subnet_5b"),
		RouteTableId: jsii.String("agent_vpc_public_rtb"),
	})
	awsec2.NewCfnSubnetRouteTableAssociation(scope, jsii.String("agent_vpc_public_subnet_5c_route_table_association"), &awsec2.CfnSubnetRouteTableAssociationProps{
		SubnetId:     jsii.String("agent_vpc_public_subnet_5c"),
		RouteTableId: jsii.String("agent_vpc_public_rtb"),
	})

	awsec2.NewCfnInternetGateway(scope, jsii.String("agent_vpc_igw"), &awsec2.CfnInternetGatewayProps{})

	// Create an Egress-Only Internet Gateway and attach it to the VPC
	awsec2.NewCfnEgressOnlyInternetGateway(scope, jsii.String("agent_vpc_egress_only_igw"), &awsec2.CfnEgressOnlyInternetGatewayProps{
		VpcId: vpc.VpcId(),
	})

	awsec2.NewCfnVPCGatewayAttachment(scope, jsii.String("agent_vpc_igw_attachment"), &awsec2.CfnVPCGatewayAttachmentProps{
		VpcId:             vpc.VpcId(),
		InternetGatewayId: jsii.String("agent_vpc_igw"),
	})
	awsec2.NewCfnVPCGatewayAttachment(scope, jsii.String("agent_vpc_egress_only_igw_attachment"), &awsec2.CfnVPCGatewayAttachmentProps{
		VpcId:             vpc.VpcId(),
		InternetGatewayId: jsii.String("agent_vpc_egress_only_igw"),
	})

	awsec2.NewCfnGatewayRouteTableAssociation(scope, jsii.String("agent_vpc_igw_attachment_route_table_association"), &awsec2.CfnGatewayRouteTableAssociationProps{
		GatewayId:    jsii.String("agent_vpc_igw"),
		RouteTableId: jsii.String("agent_vpc_public_rtb"),
	})
	awsec2.NewCfnGatewayRouteTableAssociation(scope, jsii.String("agent_vpc_egress_only_igw_attachment_route_table_association"), &awsec2.CfnGatewayRouteTableAssociationProps{
		GatewayId:    jsii.String("agent_vpc_egress_only_igw"),
		RouteTableId: jsii.String("agent_vpc_private_rtb"),
	})

	// Explicitly add a route for internet-bound traffic in the public route table:
	awsec2.NewCfnRoute(scope, jsii.String("agent_vpc_public_rtb_default_route"), &awsec2.CfnRouteProps{
		RouteTableId:         jsii.String("agent_vpc_public_rtb"),
		DestinationCidrBlock: jsii.String("0.0.0.0/0"),
		GatewayId:            jsii.String("agent_vpc_igw"),
	})

	// For IPv6, if needed, add a route for ::/0 to the IGW as well.
	awsec2.NewCfnRoute(scope, jsii.String("agent_vpc_public_rtb_default_route_ipv6"), &awsec2.CfnRouteProps{
		RouteTableId:             jsii.String("agent_vpc_public_rtb"),
		DestinationIpv6CidrBlock: jsii.String("::/0"),
		GatewayId:                jsii.String("agent_vpc_igw"),
	})

	return vpc
}

func main() {
	defer jsii.Close()

	app := awscdk.NewApp(nil)

	// stack := NewDeploymentStack(app, "cam_footage_activities_analyser_agent", &DeploymentStackProps{
	// 	awscdk.StackProps{
	// 		Env: env(),
	// 	},
	// })

	NewVPC(app, "cam_footage_activities_analyser_agent_vpc")

	// dependenciesLayer := awslambda.NewLayerVersion(stack, jsii.String(
	// 	"camFootageActivitiesAnalyserAgentDependenciesLayer",
	// ), &awslambda.LayerVersionProps{
	// 	Code: awslambda.NewAssetCode(jsii.String("../dependencies.zip"),
	// 		nil,
	// 	),
	// })

	// awslambda.NewFunction(stack, jsii.String("camFootageActivitiesAnalyserAgent"), &awslambda.FunctionProps{
	// 	Code: awslambda.NewAssetCode(jsii.String("../functions.zip"),
	// 		nil,
	// 	),
	// 	Handler: jsii.String("agent.handler"),
	// 	Runtime: awslambda.Runtime_PYTHON_3_13(),
	// 	Layers:  &[]awslambda.ILayerVersion{dependenciesLayer},
	// 	Vpc:     vpc,
	// })

	app.Synth(nil)
}

// env determines the AWS environment (account+region) in which our stack is to
// be deployed. For more information see: https://docs.aws.amazon.com/cdk/latest/guide/environments.html
func env() *awscdk.Environment {
	// If unspecified, this stack will be "environment-agnostic".
	// Account/Region-dependent features and context lookups will not work, but a
	// single synthesized template can be deployed anywhere.
	//---------------------------------------------------------------------------
	return nil

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
	// return &awscdk.Environment{
	//  Account: jsii.String(os.Getenv("CDK_DEFAULT_ACCOUNT")),
	//  Region:  jsii.String(os.Getenv("CDK_DEFAULT_REGION")),
	// }
}
